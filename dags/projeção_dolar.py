from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta
import pandas as pd
from sklearn.linear_model import LinearRegression
import numpy as np

@dag(
    schedule=None,
    start_date=datetime.now() - timedelta(days=1),
    catchup=False,
    tags=["dolar", "projecao", "serie_temporal"]
)
def dolar_projecao():

    @task
    def ler_dados():
        hook = PostgresHook(postgres_conn_id="postgres")
        sql = "SELECT date, rate FROM currency_rate ORDER BY date"
        df = hook.get_pandas_df(sql)
        df['ds'] = pd.to_datetime(df['date'])
        df['y'] = df['rate']
        return df[['ds', 'y']].to_json(date_format='iso')

    @task
    def criar_tabela_previsao():
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS currency_rate_forecast (
            id SERIAL PRIMARY KEY,
            ds DATE UNIQUE,
            yhat NUMERIC,
            yhat_lower NUMERIC,
            yhat_upper NUMERIC,
            inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        hook = PostgresHook(postgres_conn_id="postgres")
        hook.run(create_table_sql)

    @task
    def gerar_previsao(df_json: str):
        df = pd.read_json(df_json)
        df['ds'] = pd.to_datetime(df['ds'])
        df['timestamp'] = df['ds'].astype(np.int64) // 10**9  # segundos desde época

        # Treina modelo linear
        X = df[['timestamp']]
        y = df['y']
        model = LinearRegression()
        model.fit(X, y)

        # Gera datas futuras
        last_date = df['ds'].max()
        future_dates = [last_date + timedelta(days=i) for i in range(1, 31)]
        future_timestamps = np.array([d.timestamp() for d in future_dates]).reshape(-1, 1)
        y_pred = model.predict(future_timestamps)

        forecast_df = pd.DataFrame({
            'ds': future_dates,
            'yhat': y_pred,
            'yhat_lower': y_pred - 0.5,  # margem fictícia
            'yhat_upper': y_pred + 0.5
        })

        return forecast_df.to_json(date_format='iso')

    @task
    def salvar_previsao(forecast_json: str):
        forecast_df = pd.read_json(forecast_json)
        forecast_df['ds'] = pd.to_datetime(forecast_df['ds'])  # garante datetime
        hook = PostgresHook(postgres_conn_id="postgres")
        conn = hook.get_conn()
        cursor = conn.cursor()

        for _, row in forecast_df.iterrows():
            # Usa .date() para passar só a parte da data
            ds_date = row['ds'].date() if hasattr(row['ds'], 'date') else row['ds']
            cursor.execute("""
                INSERT INTO currency_rate_forecast (ds, yhat, yhat_lower, yhat_upper)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ds) DO UPDATE SET
                    yhat = EXCLUDED.yhat,
                    yhat_lower = EXCLUDED.yhat_lower,
                    yhat_upper = EXCLUDED.yhat_upper,
                    inserted_at = CURRENT_TIMESTAMP;
            """, (ds_date, row['yhat'], row['yhat_lower'], row['yhat_upper']))

        conn.commit()
        cursor.close()
        conn.close()


    criar_tabela_previsao()
    dados = ler_dados()
    previsao = gerar_previsao(dados)
    salvar_previsao(previsao)

dolar_projecao()
