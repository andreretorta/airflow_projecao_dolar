from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from datetime import datetime, timedelta
import requests

@dag(
    schedule=None,
    start_date=datetime.now() - timedelta(days=1),
    catchup=False,
    tags=["dolar", "bacen", "historico"]
)

def dolar_historico():

    # Criação da tabela
    create_table = SQLExecuteQueryOperator(
        task_id="create_table",
        conn_id="postgres",
        sql="""
        CREATE TABLE IF NOT EXISTS currency_rate (
            id SERIAL PRIMARY KEY,
            date DATE UNIQUE,
            rate NUMERIC,
            inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    @task
    def coleta_historico_api(data_inicial: str, data_final: str):
        """Coleta histórico de dólar entre duas datas."""
        url = (
            f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados"
            f"?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"
        )
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        historico = []
        for item in data:
            data_formatada = datetime.strptime(item["data"], "%d/%m/%Y").date()
            valor_formatado = float(item["valor"].replace(",", "."))
            historico.append((data_formatada, valor_formatado))
        return historico

    @task
    def insere_base_dados(historico: list):
        """Insere os dados no Postgres."""
        hook = PostgresHook(postgres_conn_id="postgres")
        conn = hook.get_conn()
        cursor = conn.cursor()

        for data, valor in historico:
            cursor.execute(
                """
                INSERT INTO currency_rate (date, rate)
                VALUES (%s, %s)
                ON CONFLICT (date) DO NOTHING;
                """,
                (data, valor)
            )

        conn.commit()
        cursor.close()
        conn.close()

    # Parâmetros: defina o intervalo de datas aqui (pode vir de variável depois)
    data_ini = "01/01/2024"
    data_fim = datetime.today().strftime("%d/%m/%Y")

    # Encadeamento
    create_table >> insere_base_dados(coleta_historico_api(data_ini, data_fim))

dolar_historico()
