WITH
  filtered AS (
    SELECT asset_id, name, meta_insert_timestamp, usage_rights, locations
    FROM `articlepicture-dam-p-f8d5.article_picture_dam_srv.article_picture`
    WHERE
      asset_state = 'Enriched'
      AND ENDS_WITH(name, '.jpg')
      AND file_size > 0
  ),
  candidates AS (
    SELECT DISTINCT
      f.asset_id,
      f.name,
      l.path,
      f.meta_insert_timestamp
    FROM
      filtered AS f
    CROSS JOIN UNNEST(f.locations) AS l
    WHERE
      l.id = 'PublicAssetService'
      AND EXISTS(
        SELECT 1 FROM UNNEST(f.usage_rights) AS u WHERE u.channel = 'hm.com'
      )
  )
SELECT c.*
FROM candidates AS c
LEFT JOIN `$tracking_table` AS t USING (asset_id, meta_insert_timestamp)
WHERE t.asset_id IS NULL
