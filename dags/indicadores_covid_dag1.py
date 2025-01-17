from airflow.decorators import task, dag
from airflow.operators.dummy import DummyOperator
from airflow.models import Variable
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from datetime import datetime

import boto3

aws_access_key_id = Variable.get('aws_access_key_id')
aws_secret_access_key = Variable.get('aws_secret_access_key')

client = boto3.client(
    'emr', region_name='us-east-1',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key
)

default_args = {
    'owner': 'Ricardo_Sylvio',
    'start_date': datetime(2022, 4, 2)
}

@dag(
    default_args=default_args, 
    schedule_interval="@once", 
    description="Executa o job Spark 1 no EMR do trabalho final", 
    catchup=False, 
    tags=['DAG1', 'Spark','EMR'])
def dag_1():

    inicio = DummyOperator(task_id='inicio')

    @task
    def tarefa_inicial():
        print("Começou!!")

    @task
    def emr_create_cluster():
        cluster_id = client.run_job_flow( # Cria um cluster EMR
            Name='Automated_EMR_Ricardo_Sylvio',
            ServiceRole='EMR_DefaultRole',
            JobFlowRole='EMR_EC2_DefaultRole',
            VisibleToAllUsers=True,
            LogUri='s3://airflow-logs-808833868807/logs/',
            ReleaseLabel='emr-6.8.0',
            Instances={
                'InstanceGroups': [
                    {
                        'Name': 'Master nodes',
                        'Market': 'ON_DEMAND',
                        'InstanceRole': 'MASTER',
                        'InstanceType': 'm5.xlarge',
                        'InstanceCount': 1,
                    },
                    {
                        'Name': 'Worker nodes',
                        'Market': 'ON_DEMAND',
                        'InstanceRole': 'CORE',
                        'InstanceType': 'm5.xlarge',
                        'InstanceCount': 1,
                    }
                ],
                'Ec2KeyName': 'keypairs-pucminas-testes',
                'KeepJobFlowAliveWhenNoSteps': True,
                'TerminationProtected': False,
                'Ec2SubnetId': 'subnet-05aaae4f0b25e38a2'
            },

            Applications=[{'Name': 'Spark'}, {'Name': 'Hive'}, {'Name':'JupyterEnterpriseGateway'} ],
        )
        return cluster_id["JobFlowId"]


    @task
    def wait_emr_cluster(cid: str):
        waiter = client.get_waiter('cluster_running')

        waiter.wait(
            ClusterId=cid,
            WaiterConfig={
                'Delay': 30,
                'MaxAttempts': 60
            }
        )
        return True


    
    @task
    def emr_process_covid1(cid: str):
        newstep = client.add_job_flow_steps(
            JobFlowId=cid,
            Steps=[
                {
                    'Name': 'Processa indicadores covid',
                    'ActionOnFailure': "CONTINUE",
                    'HadoopJarStep': {
                        'Jar': 'command-runner.jar',
                        'Args': ['spark-submit',
                                '--master', 'yarn',
                                '--deploy-mode', 'cluster',
                                '--packages', 'io.delta:delta-core_2.12:2.1.0',
                                's3://datalake-ricardo-pucminas-808833868807/jobs_spark/job_spark1_covid.py'
                                ]
                    }
                }
            ]
        )
        return newstep['StepIds'][0]

    @task
    def wait_emr_job1(cid: str, stepId: str):
        waiter = client.get_waiter('step_complete')

        waiter.wait(
            ClusterId=cid,
            StepId=stepId,
            WaiterConfig={
                'Delay': 10,
                'MaxAttempts': 600
            }
        )
        return True

    @task
    def emr_process_covid2(cid: str):
        newstep = client.add_job_flow_steps(
            JobFlowId=cid,
            Steps=[
                {
                    'Name': 'Processa Consolidação dos indicadores covid',
                    'ActionOnFailure': "CONTINUE",
                    'HadoopJarStep': {
                        'Jar': 'command-runner.jar',
                        'Args': ['spark-submit',
                                '--master', 'yarn',
                                '--deploy-mode', 'cluster',
                                '--packages', 'io.delta:delta-core_2.12:2.1.0',
                                's3://datalake-ricardo-pucminas-808833868807/jobs_spark/job_spark2_covid.py'
                                ]
                    }
                }
            ]
        )
        return newstep['StepIds'][0]

    @task
    def wait_emr_job2(cid: str, stepId: str):
        waiter = client.get_waiter('step_complete')

        waiter.wait(
            ClusterId=cid,
            StepId=stepId,
            WaiterConfig={
                'Delay': 10,
                'MaxAttempts': 600
            }
        )
        return True
    
    @task
    def terminate_emr_cluster(cid: str):
        res = client.terminate_job_flows(
            JobFlowIds=[cid]
        )

    fim = DummyOperator(task_id="fim")


    # Orquestração
    tarefainicial = tarefa_inicial()
    cluster = emr_create_cluster()
    inicio >> tarefainicial >> cluster
    # inicio >> tarefainicial

    esperacluster = wait_emr_cluster(cluster)
    indicadores = emr_process_covid1(cluster) 
    esperacluster >> indicadores

    wait_step1 = wait_emr_job1(cluster, indicadores)
    indicadores_consolidado = emr_process_covid2(cluster)
    wait_step1 >> indicadores_consolidado

    wait_step2 = wait_emr_job2(cluster, indicadores_consolidado)
    wait_step2 >> fim

    # terminacluster = terminate_emr_cluster(cluster)
    # wait_step >> terminacluster >> fim
    #---------------

execucao = dag_1()
