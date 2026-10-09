PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
 role TEXT NOT NULL CHECK(role IN ('admin','captain','store')), region TEXT NOT NULL,
 password_hash TEXT NOT NULL, online INTEGER NOT NULL DEFAULT 0,
 balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),
 reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=balance),
 lat REAL, lng REAL, location_at INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, store_id TEXT NOT NULL REFERENCES users(id), region TEXT NOT NULL,
 customer_name TEXT NOT NULL, address TEXT NOT NULL, phone TEXT NOT NULL,
 fee INTEGER NOT NULL CHECK(fee>0), commission INTEGER NOT NULL,
 route_group TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', scheduled_at INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','picked_up','delivered','cancelled')),
 captain_id TEXT REFERENCES users(id), created_at INTEGER NOT NULL,
 lat REAL, lng REAL
);
CREATE TABLE IF NOT EXISTS ledger (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), amount INTEGER NOT NULL,
 kind TEXT NOT NULL, reference TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
 id TEXT PRIMARY KEY, sender_id TEXT NOT NULL REFERENCES users(id), recipient_id TEXT NOT NULL REFERENCES users(id),
 amount INTEGER NOT NULL CHECK(amount>0), idem_key TEXT NOT NULL, created_at INTEGER NOT NULL,
 UNIQUE(sender_id,idem_key)
);
CREATE TABLE IF NOT EXISTS threads (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('support','order')),
 owner_id TEXT NOT NULL REFERENCES users(id), order_id TEXT UNIQUE REFERENCES orders(id), region TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id), sender_id TEXT NOT NULL REFERENCES users(id),
 body TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, details TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_region_status ON orders(region,status);
CREATE INDEX IF NOT EXISTS orders_captain ON orders(captain_id,status);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id,created_at);
