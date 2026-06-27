# Plan: Browse + AI 平台 5 項改進

## Context

用戶測試 cinema-browse 和 cinema-api 後提出 5 項改進。
兩個平台已分別部署為獨立 Cloud Run Services。

---

## Item 1 — 時間篩選改時段下拉（browse/index.html）

**建議：4 時段**（較 3 小時一組更直觀，符合看電影習慣）

| 標籤 | 範圍 |
|------|------|
| 早上 (06-12) | 06:00–11:59 |
| 下午 (12-17) | 12:00–16:59 |
| 晚上 (17-21) | 17:00–20:59 |
| 深夜 (21-) | 21:00 以後（含凌晨 00:xx–05:59） |

**實作：** `show_time` 從 text filter → 時段 dropdown，options 為預設 4 個標籤（非從資料動態生成）。

新增 `TIME_RANGES` 常數（靜態定義），新增 `TIME_RANGE_COL = 'show_time'` 標記：

```js
const TIME_RANGES = [
  { label: '早上 (06-12)', test: t => t >= '06:00' && t < '12:00' },
  { label: '下午 (12-17)', test: t => t >= '12:00' && t < '17:00' },
  { label: '晚上 (17-21)', test: t => t >= '17:00' && t < '21:00' },
  { label: '深夜 (21-)',   test: t => t >= '21:00' || t < '06:00' },
];
```

`rowMatches` 中 show_time 分支：選中的時段集合對 test function 做 OR 邏輯（勾多個時段顯示聯集）。

`buildHeader` 中 show_time 欄使用靜態 TIME_RANGES 選項，`openDropdown` / `renderDropdownOptions` 加對應分支。

---

## Item 2 — 修正下拉「勾選 = 包含」UX（browse/index.html）

**根本原因：** 目前下拉預設「全部打勾」，點選 IMAX 實際是**取消勾選（排除 IMAX）**，
等於「顯示所有不是 IMAX 的項目」。新光本來就沒有 IMAX → 結果不變 → 「沒有反應」。

**修正：** 改為「預設全不勾」模式，勾 = 加入 include 清單。

3 處改動，其餘 applyDropdown / updateDropdownLabel 邏輯不變：

```js
// 1. renderDropdownOptions — 移除 size===0 預設全打勾
const checked = pendingSelection.has(v);
// 原: pendingSelection.size === 0 || pendingSelection.has(v)

// 2. onCbChange — 移除「全選展開」邏輯
function onCbChange(cb) {
  if (cb.checked) pendingSelection.add(cb.value);
  else pendingSelection.delete(cb.value);
}
// 原有 if (pendingSelection.size === 0) { pendingSelection = new Set(allVals); } 邏輯刪除

// 3. applyDropdown 不變 — 0 勾選 → delete dropFilters[col] (全部)
```

效果：新光篩選後 → 廳型下拉全不勾 → 勾 IMAX → 確定 → 正確顯示空表格。

---

## Item 3 — 影城改下拉（browse/index.html）

`DROPDOWN_COLS` 加入 `'theater_name'`，選項從 ALL_ROWS 動態生成（唯一值清單），支援下拉內搜尋：

```js
const DROPDOWN_COLS = new Set(['show_date','chain','theater_name','hall_type','language','is_special_hall']);
```

`hall_name` 維持 text filter（值太多，搜尋比下拉好用）。

---

## Item 4 — 各院線官網連結（browse/index.html + api/index.html）

兩個頁面的 `renderCell` 中，`chain` 欄用 `<a>` 包住既有彩色 span：

```js
const CHAIN_URLS = {
  '威秀': 'https://www.vscinemas.com.tw',
  '新光': 'https://www.skcinemas.com',
  '美麗華': 'https://www.miramarcinemas.tw',
};

// renderCell chain 分支：
if (col === 'chain' && CHAIN_COLORS[s]) {
  const url = CHAIN_URLS[s];
  const inner = `<span class="${CHAIN_COLORS[s]}">${esc(s)}</span>`;
  return url ? `<a href="${url}" target="_blank" rel="noopener">${inner}</a>` : inner;
}
```

---

## Item 5 — 新增 AI 查詢 Prompt 範例（api/index.html + api/templates.py）

### api/index.html：新增 3 個 chips（6 → 9 個）

```
今天晚上台北有什麼特殊影廳的場次？
威秀信義今天有什麼場次？
哪些電影同時有 4DX 和 IMAX 場次？
```

### api/templates.py：新增 1 個 template

```python
"evening_special_today": {
    "description": "今天晚上傍晚之後的特殊廳場次，例如 IMAX 4DX Dolby 晚上 深夜 17點後",
    "sql": """
        SELECT show_date, movie_name, theater_name, chain, hall_type, show_time, language
        FROM `{project}.{dataset}.fact_showtimes`
        WHERE show_date = CURRENT_DATE('Asia/Taipei')
          AND is_special_hall = TRUE
          AND show_time >= '17:00'
        ORDER BY chain, show_time
    """
}
```

---

## 修改檔案

| 檔案 | Items |
|------|-------|
| `browse/index.html` | 1, 2, 3, 4 |
| `api/index.html` | 4, 5 |
| `api/templates.py` | 5 |

## 部署

1. cinema-browse（Items 1-4）: `gcloud builds submit + gcloud run services update cinema-browse --region asia-east1`
2. cinema-api（Items 4-5）: `gcloud builds submit + gcloud run services update cinema-api --region asia-east1`

## 驗證

- Browse: 時段下拉 → 早上點確定 → 只有 06-12 場次；新光+IMAX → 空表格；院線名稱可點擊到官網
- AI 平台: 新 chip 送出 → 回傳正確場次；院線欄可點擊到官網
