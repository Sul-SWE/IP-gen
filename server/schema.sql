-- Database tables (MySQL 5.7+ / MariaDB 10.3+). Created by the setup page; safe to run again.
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
