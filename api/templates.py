"""
台灣影城特殊廳場次查詢 SQL 模板
每個模板提供自然語言描述（用於語意搜尋），以及對應的 SQL 骨架（供 Gemini 參考）
"""

SQL_TEMPLATES = [
    {
        "id": "special_hall_today",
        "description": "今天當日有哪些特殊廳場次？IMAX、4DX、Dolby Cinema、Gold Class 等特殊廳僅限今天的場次",
        "sql_template": """
SELECT theater_name, chain, hall_type, hall_name, movie_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date = CURRENT_DATE('Asia/Taipei')
  AND is_special_hall = TRUE
ORDER BY chain, theater_name, hall_type, show_time
""",
    },
    {
        "id": "special_hall_by_type",
        "description": "特定廳型（IMAX / 4DX / Dolby / Gold Class）的場次，某種特殊廳有哪些場次",
        "sql_template": """
SELECT show_date, theater_name, chain, hall_name, movie_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE is_special_hall = TRUE
  AND hall_type = '{hall_type}'
  AND show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 7 DAY)
ORDER BY show_date, theater_name, show_time
""",
    },
    {
        "id": "movie_showtimes",
        "description": "查詢特定電影的所有場次，某部電影在哪些院線哪些影城有上映、什麼時間播放",
        "sql_template": """
SELECT show_date, theater_name, chain, hall_type, hall_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE LOWER(movie_name) LIKE LOWER('%{movie_name}%')
  AND show_date >= CURRENT_DATE('Asia/Taipei')
ORDER BY show_date, chain, theater_name, show_time
""",
    },
    {
        "id": "chain_comparison",
        "description": "比較各院線的場次數量、特殊廳比例，院線之間的統計比較",
        "sql_template": """
SELECT
  chain,
  COUNT(*) AS total_sessions,
  COUNTIF(is_special_hall) AS special_sessions,
  ROUND(COUNTIF(is_special_hall) / COUNT(*) * 100, 1) AS special_pct,
  COUNT(DISTINCT theater_name) AS theater_count,
  COUNT(DISTINCT movie_name) AS movie_count
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date = CURRENT_DATE('Asia/Taipei')
GROUP BY chain
ORDER BY total_sessions DESC
""",
    },
    {
        "id": "special_hall_distribution",
        "description": "各種特殊廳的場次分布，不同廳型的數量統計",
        "sql_template": """
SELECT
  hall_type,
  COUNT(*) AS sessions,
  COUNT(DISTINCT theater_name) AS theaters,
  COUNT(DISTINCT movie_name) AS movies
FROM `{project}.{dataset}.fact_showtimes`
WHERE is_special_hall = TRUE
  AND show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 7 DAY)
GROUP BY hall_type
ORDER BY sessions DESC
""",
    },
    {
        "id": "language_breakdown",
        "description": "各語言場次統計，英文版、中文版、日文版的場次數量",
        "sql_template": """
SELECT
  CASE WHEN language = '' OR language IS NULL THEN '未標示' ELSE language END AS language,
  chain,
  COUNT(*) AS sessions
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date = CURRENT_DATE('Asia/Taipei')
GROUP BY language, chain
ORDER BY sessions DESC
""",
    },
    {
        "id": "theater_schedule",
        "description": "某間特定影城的場次，例如信義威秀、天母新光、獅子林、青埔、美麗華，特定影城名稱查場次排片",
        "sql_template": """
SELECT show_date, movie_name, hall_type, hall_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE theater_name LIKE '%{theater_name}%'
  AND show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 3 DAY)
ORDER BY show_date, show_time
""",
    },
    {
        "id": "upcoming_sessions",
        "description": "今天剩餘的場次，現在之後還有哪些場次可以看",
        "sql_template": """
SELECT theater_name, chain, hall_type, movie_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date = CURRENT_DATE('Asia/Taipei')
  AND show_time > FORMAT_TIMESTAMP('%H:%M', CURRENT_TIMESTAMP(), 'Asia/Taipei')
ORDER BY show_time, chain, theater_name
""",
    },
    {
        "id": "popular_movies",
        "description": "場次最多的電影排行，哪些電影最熱門，場次數量排行",
        "sql_template": """
SELECT
  movie_name,
  COUNT(*) AS sessions,
  COUNT(DISTINCT theater_name) AS theaters,
  COUNTIF(is_special_hall) AS special_sessions
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 7 DAY)
GROUP BY movie_name
ORDER BY sessions DESC
LIMIT 20
""",
    },
    {
        "id": "imax_sessions",
        "description": "IMAX場次，哪裡有IMAX，IMAX今天播什麼電影",
        "sql_template": """
SELECT show_date, theater_name, chain, hall_name, movie_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE hall_type = 'IMAX'
  AND show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 7 DAY)
ORDER BY show_date, theater_name, show_time
""",
    },
    {
        "id": "evening_special_today",
        "description": "今天晚上傍晚之後的特殊廳場次，例如 IMAX 4DX Dolby 晚上 深夜 17點後 晚上場次",
        "sql_template": """
SELECT show_date, movie_name, theater_name, chain, hall_type, show_time, language
FROM `{project}.{dataset}.fact_showtimes`
WHERE show_date = CURRENT_DATE('Asia/Taipei')
  AND is_special_hall = TRUE
  AND show_time >= '17:00'
ORDER BY chain, show_time
""",
    },
    {
        "id": "weekend_or_weekday",
        "description": "查詢週末（這週六、這週日、下週六日）或特定星期幾的場次，例如週末有哪些 IMAX 4DX 特殊廳、這週六桃園台北有什麼場次、下週五晚上有什麼電影、週末哪裡有播放某部電影",
        "sql_template": """
WITH target_dates AS (
  SELECT
    DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL MOD(7 - EXTRACT(DAYOFWEEK FROM CURRENT_DATE('Asia/Taipei')), 7) DAY) AS next_saturday,
    DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL MOD(7 - EXTRACT(DAYOFWEEK FROM CURRENT_DATE('Asia/Taipei')), 7) + 1 DAY) AS next_sunday
)
SELECT show_date, theater_name, chain, hall_type, hall_name, movie_name, show_time, language
FROM `{project}.{dataset}.fact_showtimes`, target_dates
WHERE show_date BETWEEN next_saturday AND next_sunday
ORDER BY show_date, theater_name, show_time
""",
    },
    {
        "id": "multi_hall_movies",
        "description": "同時有多種特殊廳場次的電影，哪些電影同時有 4DX 和 IMAX，跨廳型的電影",
        "sql_template": """
SELECT
  movie_name,
  STRING_AGG(DISTINCT hall_type ORDER BY hall_type) AS hall_types,
  COUNT(DISTINCT hall_type) AS hall_type_count,
  COUNT(*) AS sessions
FROM `{project}.{dataset}.fact_showtimes`
WHERE is_special_hall = TRUE
  AND show_date BETWEEN CURRENT_DATE('Asia/Taipei') AND DATE_ADD(CURRENT_DATE('Asia/Taipei'), INTERVAL 7 DAY)
GROUP BY movie_name
HAVING COUNT(DISTINCT hall_type) >= 2
ORDER BY hall_type_count DESC, sessions DESC
""",
    },
]
