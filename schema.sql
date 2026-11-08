-- Run as the MySQL administrator against the existing pythonapp database.
-- Re-running this file preserves an existing counter and test results.
CREATE TABLE IF NOT EXISTS page_counter (
    id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    visits BIGINT UNSIGNED NOT NULL DEFAULT 0,
    app_restart_result VARCHAR(255) NOT NULL DEFAULT 'Not tested yet.',
    server_restart_result VARCHAR(255) NOT NULL DEFAULT 'Not tested yet.'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO page_counter (id, visits) VALUES (1, 0)
ON DUPLICATE KEY UPDATE id = 1;
