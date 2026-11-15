-- 0002 · nonce 去重表
--
-- 应用：npx wrangler d1 execute qx-album --remote --file=./migrations/0002_add_nonce_seen.sql
-- 幂等：IF NOT EXISTS，可重复执行。
--
-- 语义：nonce 参与签名但此前不落库，因此时间窗内的同一请求可以被原样重放。
-- 这里记录已用过的 nonce，INSERT 冲突即视为重放。过期行由 auth.js 抽样清理。

CREATE TABLE IF NOT EXISTS nonce_seen (
  nonce TEXT PRIMARY KEY,
  ts    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nonce_seen_ts ON nonce_seen(ts);
