"""Full WeatherNext 3 gridded data on Google Cloud (requires approved access).

Request access: https://developers.google.com/weathernext/guides/access-forecast
(one Google Form; approval takes ~5-7 business days and unlocks BigQuery, Earth Engine
and Cloud Storage together). Then subscribe to the dataset in BigQuery Analytics Hub.

Install extras first:  pip install google-cloud-bigquery db-dtypes
Authenticate:          gcloud auth application-default login
"""

from __future__ import annotations

# Surfaces once access is granted:
GCS_ENSEMBLE = "gs://weathernext3_spatial/"             # raw 64-member Zarr incl. pressure levels
GCS_STATISTICS = "gs://weathernext3_statistics_spatial/"  # precomputed mean/percentiles
BQ_TABLE_0P1 = "weathernext_3_0_0_0p1deg"    # 0.1° gridded surface statistics
BQ_TABLE_0P05 = "weathernext_3_0_0_0p05deg"  # 0.05° station-resolution statistics

POINT_SQL = """
SELECT t.init_time, f.time AS valid_time, f.hours AS lead_hours,
       f.wind_speed_10m_mean, f.wind_speed_10m_p10, f.wind_speed_10m_p90,
       f.mean_sea_level_pressure_mean, f.total_precipitation_1hr_mean
FROM `{project}.{dataset}.{table}` AS t, t.forecast AS f
WHERE t.init_time = (SELECT MAX(init_time) FROM `{project}.{dataset}.{table}`
                     WHERE init_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY))
  AND ST_INTERSECTS(t.geography_polygon, ST_GEOGPOINT(@lon, @lat))
ORDER BY valid_time
"""


def point_forecast(project: str, dataset: str, lat: float, lon: float, table: str = BQ_TABLE_0P1):
    """Latest WeatherNext 3 ensemble statistics for the grid cell containing (lat, lon)."""
    from google.cloud import bigquery  # optional dependency

    client = bigquery.Client(project=project)
    job = client.query(
        POINT_SQL.format(project=project, dataset=dataset, table=table),
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lat", "FLOAT64", lat),
            bigquery.ScalarQueryParameter("lon", "FLOAT64", lon),
        ]),
    )
    return job.to_dataframe()
