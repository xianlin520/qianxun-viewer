-- 0001 · 短链可选过期时间
--
-- 应用：npx wrangler d1 execute qx-album --remote --file=./migrations/0001_add_expires_at.sql
-- 幂等：重复执行会因列已存在而报错，属预期，可忽略。
--
-- 语义：NULL = 长期有效（与旧版行为一致）；非 NULL = 到该毫秒即失效。

ALTER TABLE shares ADD COLUMN expires_at INTEGER;

CREATE INDEX IF NOT EXISTS idx_shares_created ON shares(created_at);
