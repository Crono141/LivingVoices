-- living_voices_report -- a voice-over line a player marked as wrong in game (2026-10-31, the producer: "the one-off
-- errors I find I can note immediately"). The Living Voices add-on's "/lv bad <note>" whispers the realm on the
-- addon channel (prefix LVR); server/lua/living_voices_report.lua checks it and writes one row here. Who reported it
-- (account, character, race, class, sex) is taken from the server's own player object, not from the message.
-- tools/import_reports.py reads new rows (a read-only login) and puts each line on the review page with its note.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS. The Lua writes this table, so it must exist before 'lua' installs the
-- script (check_lua_tables refuses otherwise): run 'content-sql' first, then 'lua', then 'reload ale'.

USE acore_characters;

CREATE TABLE IF NOT EXISTS `living_voices_report` (
  `id`            INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  `reported_at`   DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `account`       INT UNSIGNED     NOT NULL,
  `guid`          INT UNSIGNED     NOT NULL,
  `char_name`     VARCHAR(12)      NOT NULL DEFAULT '',
  `race`          TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `class`         TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `gender`        TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `line`          VARCHAR(64)      NOT NULL,
  `npc`           VARCHAR(64)      NOT NULL DEFAULT '',
  `title`         VARCHAR(128)     NOT NULL DEFAULT '',
  `zone`          VARCHAR(64)      NOT NULL DEFAULT '',
  `note`          VARCHAR(255)     NOT NULL DEFAULT '',
  `addon_version` VARCHAR(16)      NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_reported_at` (`reported_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Living Voices: voice-over lines reported in game (/lv bad)';
