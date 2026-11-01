-- Weekly net demand for the top 25 products, one row per product per week (zero filled).
-- Weeks run Monday to Sunday. Only the 104 complete weeks are used:
-- 7 Dec 2009 to 4 Dec 2011 (the first and last weeks in the data are part weeks).
WITH RECURSIVE weeks(week_start) AS (
    SELECT DATE('2009-12-07')
    UNION ALL
    SELECT DATE(week_start, '+7 days') FROM weeks WHERE week_start < DATE('2011-11-28')
),
product_week AS (
    SELECT stock_code, week_start, SUM(quantity) AS net_qty
    FROM sales_lines
    WHERE week_start BETWEEN '2009-12-07' AND '2011-11-28'
    GROUP BY stock_code, week_start
),
product_stats AS (
    SELECT stock_code,
           SUM(net_qty) AS total_qty,
           SUM(CASE WHEN net_qty > 0 THEN 1 ELSE 0 END) AS weeks_with_sales
    FROM product_week
    GROUP BY stock_code
),
top_products AS (
    -- Top 25 by volume among products that sold in at least 95 of the 104 weeks,
    -- so every product has a full history to forecast from.
    SELECT stock_code, total_qty, weeks_with_sales
    FROM product_stats
    WHERE weeks_with_sales >= 95
    ORDER BY total_qty DESC
    LIMIT 25
),
names AS (
    -- most common description for each code (some codes have several spellings)
    SELECT stock_code, description FROM (
        SELECT stock_code, description,
               ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY COUNT(*) DESC) AS rn
        FROM sales_lines WHERE description IS NOT NULL
        GROUP BY stock_code, description
    ) WHERE rn = 1
)
SELECT t.stock_code,
       n.description,
       w.week_start,
       MAX(COALESCE(pw.net_qty, 0), 0) AS demand   -- a week with more returns than sales counts as 0
FROM top_products t
CROSS JOIN weeks w
LEFT JOIN product_week pw ON pw.stock_code = t.stock_code AND pw.week_start = w.week_start
LEFT JOIN names n ON n.stock_code = t.stock_code
ORDER BY t.total_qty DESC, w.week_start;
