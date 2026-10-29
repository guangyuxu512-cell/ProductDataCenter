INSERT INTO collector_settings (setting_key, setting_value) VALUES
  ('phone_cleanup', '{"enabled":true,"acknowledged_batch_size":10,"keep_recent":3}'::jsonb),
  ('retry_policy', '{"max_attempts":3,"delays_seconds":[5,15,30]}'::jsonb)
ON CONFLICT (setting_key) DO NOTHING;

