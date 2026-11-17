-- =====================================================================
--  IP Generator - database (MySQL 5.7+ / MariaDB 10.3+)
--  1) Tables   2) Starting rules (DUMMY TEST VALUES from the SRS)
--
--  The setup page runs this file automatically. You can also import it
--  yourself in phpMyAdmin: create/select the database (e.g. ipgen), then
--  Import > this file. Running it again is safe: nothing is duplicated.
--  The admin account is created by the setup page (password is hashed).
-- =====================================================================

-- ------------------------------------------------------------------ 1) Tables
CREATE TABLE IF NOT EXISTS accounts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(40) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(10) NOT NULL DEFAULT 'admin',
  active TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
  id VARCHAR(64) PRIMARY KEY,
  account_id INT NOT NULL,
  csrf VARCHAR(64) NOT NULL,
  created_at DATETIME NOT NULL,
  last_seen DATETIME NOT NULL,
  ip VARCHAR(45) NOT NULL DEFAULT '',
  ended_reason VARCHAR(20) NOT NULL DEFAULT '',
  CONSTRAINT fk_sessions_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS login_failures (
  id INT AUTO_INCREMENT PRIMARY KEY,
  ip VARCHAR(45) NOT NULL,
  at DATETIME NOT NULL,
  INDEX ix_login_failures_ip (ip)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS facilities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(8) NOT NULL UNIQUE,
  active TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS gcp_rings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(40) NOT NULL UNIQUE,
  octet1 INT NOT NULL,
  octet2 INT NOT NULL,
  rtu_vlan VARCHAR(4) NOT NULL,
  plc_vlan VARCHAR(4) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_gcp_octets (octet1, octet2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS vendors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(30) NOT NULL UNIQUE,
  capacity INT NOT NULL,
  octets TEXT NOT NULL,
  fields TEXT NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS blocks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  gcp_id INT NOT NULL,
  vendor_id INT NOT NULL,
  seq INT NOT NULL,
  status VARCHAR(10) NOT NULL,
  octets TEXT NOT NULL,
  created_at DATETIME NOT NULL,
  activated_at DATETIME NULL,
  UNIQUE KEY uq_block_seq (gcp_id, vendor_id, seq),
  CONSTRAINT fk_blocks_gcp FOREIGN KEY (gcp_id) REFERENCES gcp_rings(id),
  CONSTRAINT fk_blocks_vendor FOREIGN KEY (vendor_id) REFERENCES vendors(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS block_octets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  gcp_id INT NOT NULL,
  octet3 INT NOT NULL,
  block_id INT NOT NULL,
  UNIQUE KEY uq_gcp_octet3 (gcp_id, octet3),
  CONSTRAINT fk_block_octets_gcp FOREIGN KEY (gcp_id) REFERENCES gcp_rings(id),
  CONSTRAINT fk_block_octets_block FOREIGN KEY (block_id) REFERENCES blocks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS records (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  name_key VARCHAR(40) NULL UNIQUE,          -- lower-case real name; NULL for placeholders, which may repeat
  gcp_code VARCHAR(40) NOT NULL DEFAULT '',
  vendor VARCHAR(30) NOT NULL DEFAULT '',
  block_id INT NULL,
  host_no INT NULL,
  engineer_name VARCHAR(40) NOT NULL DEFAULT '',
  record_date VARCHAR(20) NOT NULL DEFAULT '',
  status VARCHAR(10) NOT NULL DEFAULT 'active',
  shared_fields TEXT NOT NULL,
  import_batch_id VARCHAR(40) NULL,
  version INT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  deleted_at DATETIME NULL,
  deleted_by VARCHAR(40) NOT NULL DEFAULT '',
  INDEX ix_records_gcp_code (gcp_code),
  INDEX ix_records_status (status),
  INDEX ix_records_import_batch_id (import_batch_id),
  CONSTRAINT fk_records_block FOREIGN KEY (block_id) REFERENCES blocks(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ip_assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  record_id INT NOT NULL,
  field VARCHAR(30) NOT NULL,
  ip VARCHAR(15) NOT NULL,
  uniq_ip VARCHAR(15) NULL UNIQUE,           -- device IPs (active and trashed records); NULL for shared gateway/laptop IPs
  UNIQUE KEY uq_record_field (record_id, field),
  INDEX ix_ip_assignments_ip (ip),
  CONSTRAINT fk_ip_record FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  at DATETIME NOT NULL,
  role VARCHAR(10) NOT NULL DEFAULT 'admin',
  engineer_name VARCHAR(40) NOT NULL,
  action VARCHAR(30) NOT NULL,
  record_name VARCHAR(90) NOT NULL DEFAULT '',
  details TEXT NOT NULL,
  import_batch_id VARCHAR(40) NULL,
  INDEX ix_audit_log_at (at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS settings (
  name VARCHAR(40) PRIMARY KEY,
  value VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------ 2) Starting rules
-- Settings: the write lock row (serialises all changes), warning level (90%), subnet mask
INSERT IGNORE INTO settings (name, value) VALUES
  ('write_lock', '1'), ('warn_at', '0.9'), ('subnet_mask', '255.255.255.0');

-- Facilities (first part of a facility name, e.g. UTMN-1000)
INSERT IGNORE INTO facilities (id, code, active) VALUES
  (1, 'UTMN', 1), (2, 'HRDH', 1), (3, 'HWYH', 1), (4, 'SDGM', 1);

-- GCP & Rings: first two octets of every address, and the VLANs
INSERT IGNORE INTO gcp_rings (id, code, octet1, octet2, rtu_vlan, plc_vlan, active) VALUES
  (1, 'HDGCP1-R1', 18, 1, '1800', '1801', 1),
  (2, 'SHGCP1-R1', 19, 1, '1810', '1811', 1),
  (3, 'HWGCP1-R1', 20, 1, '1820', '1821', 1),
  (4, 'UTGCP1-R1', 21, 1, '1830', '1831', 1);

-- Vendors: every address = host number n multiplied by a, plus b, on network A, B or M (Moxa).
-- octets = default third octet of each network for a new GCP & Ring.
INSERT IGNORE INTO vendors (id, name, capacity, octets, fields, active) VALUES
  (1, 'Yokogawa', 39, '{"A":20,"B":21,"M":10}',
   '[{"field":"RTU IP-1","net":"A","a":1,"b":168},{"field":"RTU IP-2","net":"B","a":1,"b":168},{"field":"PLC IP-1","net":"A","a":1,"b":84},{"field":"PLC IP-2","net":"B","a":1,"b":84},{"field":"RTU Internal IP-1","net":"A","a":1,"b":0},{"field":"RTU Internal IP-2","net":"B","a":1,"b":0},{"field":"RTU-HMI IP","net":"A","a":1,"b":210},{"field":"IES Moxa IP","net":"M","a":1,"b":0},{"field":"Engg. Laptop IP","net":"A","a":0,"b":250},{"field":"Gateway-1","net":"A","a":0,"b":253},{"field":"Gateway-2","net":"B","a":0,"b":253}]', 1),
  (2, 'Honeywell', 62, '{"A":100,"B":101,"M":11}',
   '[{"field":"RTU IP-1","net":"A","a":4,"b":-3},{"field":"RTU IP-2","net":"A","a":4,"b":-2},{"field":"PLC IP-1","net":"A","a":4,"b":-1},{"field":"PLC IP-2","net":"A","a":4,"b":0},{"field":"RTU-HMI IP","net":"B","a":1,"b":0},{"field":"IES Moxa IP","net":"M","a":1,"b":0},{"field":"Engg. Laptop IP","net":"A","a":0,"b":250},{"field":"Gateway-1","net":"A","a":0,"b":253},{"field":"Gateway-2","net":"B","a":0,"b":253}]', 1);

-- Address blocks: one active block per GCP & Ring + vendor (third octets it uses)
INSERT IGNORE INTO blocks (id, gcp_id, vendor_id, seq, status, octets, created_at, activated_at) VALUES
  (1, 1, 1, 1, 'active', '{"A":20,"B":21,"M":10}', NOW(), NOW()),
  (2, 1, 2, 1, 'active', '{"A":100,"B":101,"M":11}', NOW(), NOW()),
  (3, 2, 1, 1, 'active', '{"A":20,"B":21,"M":10}', NOW(), NOW()),
  (4, 2, 2, 1, 'active', '{"A":100,"B":101,"M":11}', NOW(), NOW()),
  (5, 3, 1, 1, 'active', '{"A":20,"B":21,"M":10}', NOW(), NOW()),
  (6, 3, 2, 1, 'active', '{"A":100,"B":101,"M":11}', NOW(), NOW()),
  (7, 4, 1, 1, 'active', '{"A":20,"B":21,"M":10}', NOW(), NOW()),
  (8, 4, 2, 1, 'active', '{"A":100,"B":101,"M":11}', NOW(), NOW());

-- Which third octets are taken in each GCP & Ring (a third octet can belong to one block only)
INSERT IGNORE INTO block_octets (gcp_id, octet3, block_id) VALUES
  (1, 20, 1), (1, 21, 1), (1, 10, 1),
  (1, 100, 2), (1, 101, 2), (1, 11, 2),
  (2, 20, 3), (2, 21, 3), (2, 10, 3),
  (2, 100, 4), (2, 101, 4), (2, 11, 4),
  (3, 20, 5), (3, 21, 5), (3, 10, 5),
  (3, 100, 6), (3, 101, 6), (3, 11, 6),
  (4, 20, 7), (4, 21, 7), (4, 10, 7),
  (4, 100, 8), (4, 101, 8), (4, 11, 8);
