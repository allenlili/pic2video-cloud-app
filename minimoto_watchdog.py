#!/usr/bin/python3
import boto3, botocore
import configparser
import sys
import time
import os
from datetime import datetime
from datetime import timedelta
from operator import itemgetter
import pickle

# def write_config(handle, instance_configure_file):
#     config_file = open(instance_configure_file, 'w')
#     handle.write(config_file)
#     config_file.close()
#     handle = configparser.ConfigParser()
#     handle.read(instance_configure_file)
#     return handle

option = None
if len(sys.argv[1:]) != 0:
    option = sys.argv[1:][0]
    if option != "--status":
        print("watchdog: args error, arg should be --status")
        exit(-1)

configure_file = "configure.ini"
config = configparser.ConfigParser()
config.read(configure_file)
# INIT
key_file = config["INIT"]["key_file"]
key_file_name = config["INIT"]["key_file_name"]
region_name = config["INIT"]["region_name"]
aws_access_key = config["INIT"]["aws_access_key"]
aws_secret_access_key = config["INIT"]["aws_secret_access_key"]
service_ec2_type = config['INIT']['service_ec2_type']
service_identity = config['EC2']['SERVICE_IDENTITY']
# sg
sg_id = config["SECURITY_GROUP"]["security_group_id"]
# SQS
queue_url = config["SQS"]["queue_url"]
queue_name = config["SQS"]["queue_name"]
# EC2
client_instance_id = config['EC2']['client_id']
watchdog_instance_id = config['EC2']['watchdog_id']
service_instance_id = config['EC2']['service_id']
# AMI
service_ami = config["AMI"]["service_ami"]

# instance_configure_file = "instance_record.ini"
# record_config = configparser.ConfigParser()
# record_config = write_config(record_config, instance_configure_file)

# ------------------------------   SESSION   ------------------------------
boto3.setup_default_session(
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name)
session = boto3.DEFAULT_SESSION

ec2_resource = session.resource(service_name="ec2")
ec2_client = session.client(service_name="ec2")
sqs_resource = session.resource(service_name='sqs')
sqs_client = session.client(service_name='sqs')
cloud_watch_resource = session.resource(service_name='cloudwatch')
cloud_watch_client = session.client(service_name='cloudwatch')


def write_config(handle):
    config_file = open('configure.ini', 'w')
    handle.write(config_file)
    config_file.close()
    handle = configparser.ConfigParser()
    handle.read("configure.ini")
    return handle


def get_services_cpu_utilisation_metrics(_status=None):
    _reservations = ec2_client.describe_instances(
        Filters=(
            {'Name': 'instance-state-name', 'Values': ['running', 'stopped']},
            {'Name': 'tag:Name', 'Values': [service_identity]}
        )
    )
    real = datetime.utcnow()
    begin = (real - timedelta(minutes=11)).isoformat()
    end = (real + timedelta(seconds=30)).isoformat()
    [count, aggregate, cpu_max_min, aggregate_max_cpu, average_cpu_list] = 0, 0, [], 0, []
    for _reservation in _reservations['Reservations']:
        _service_instances = _reservation['Instances']
        for _inst in _service_instances:
            _instance_id = _inst['InstanceId']
            results = cloud_watch_client.get_metric_statistics(
                Namespace='AWS/EC2', MetricName="CPUUtilization",
                StartTime=begin, EndTime=end,
                Dimensions=[{'Name': 'InstanceId', 'Value': _instance_id}],
                Period=60, Statistics=['Average', 'Maximum', 'Minimum'])
            data_points = results['Datapoints']
            if len(data_points) > 0:
                recent = sorted(data_points, key=itemgetter('Timestamp'))[-1]
                average_u, max_u, min_u = recent['Average'], recent['Maximum'], recent['Minimum']
                count += 1
                aggregate += average_u
                aggregate_max_cpu += max_u
                state = _inst['State']['Name']
                cpu_max_min.append((_instance_id, max_u, min_u))
                average_cpu_list.append((_instance_id, average_u))
                if _status == "--status":
                    print("instance: <{}> <{}> <{}>".format(_instance_id, state, '%.2f' % average_u + "%"))
            else:
                print("watchdog: data not available now, please do watchdog again...")
                exit(0)
    if count < 1:
        print("watchdog: data not available now, please do watchdog again...")
        exit(0)
    average_utilization = aggregate / count
    if _status == "--status":
        print('average_utilization: <{}>'.format('%.2f' % average_utilization + "%"))
    return [average_utilization, cpu_max_min, count, aggregate_max_cpu, average_cpu_list]


def scale_out(num=1, regular=None):
    print("watchdog: scaling out ...")
    instance = None
    for i in range(num):
        try:
            instances = ec2_resource.create_instances(
                ImageId=service_ami, MinCount=1, MaxCount=1, KeyName=key_file_name,
                SecurityGroupIds=[sg_id], InstanceType=service_ec2_type, Monitoring={'Enabled': True},
                TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': service_identity}]}]
            )
            instance = instances[0]
        except botocore.exceptions.ClientError as err:
            print("watchdog:", err.response["Error"]["Message"])
            exit(0)
        try:
            instance.wait_until_running()
        except:
            print('watchdog: fail to add a new instance...exit')
            raise SystemExit
        while instance.public_dns_name == "" or instance.public_dns_name is None:
            time.sleep(5)
            instance.reload()
        while True:
            _mark = 1
            _resp = ec2_client.describe_instance_status(InstanceIds=[instance.instance_id])
            for _status in _resp.get('InstanceStatuses'):
                if _status['InstanceState']['Name'] != "running":
                    _mark = 0
                if _status['SystemStatus']['Status'] != "ok":
                    _mark = 0
                if _status['SystemStatus']['Details'][0]['Status'] != 'passed':
                    _mark = 0
                if _status['InstanceStatus']['Details'][0]['Status'] != 'passed':
                    _mark = 0
            if _mark == 1:
                print("watchdog: a new service node can be reached now")
                if regular is True:
                    global config
                    config['EC2']['service_id'] = instance.instance_id
                    config = write_config(config)
                break
            time.sleep(3)
        os.system("scp -o StrictHostKeyChecking=no -i " + key_file + " " + configure_file +
                  " ubuntu@" + instance.public_dns_name + ":~")


def scale_in(num=1):
    print("watchdog: scaling in ...")
    for i in range(num):
        instance_lists = ec2_resource.instances.filter(Filters=(
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'tag:Name', 'Values': [service_identity]}
        ))
        for each in instance_lists:
            if each.id != service_instance_id and each.id != client_instance_id and each.id != watchdog_instance_id:
                each.terminate()
                while True:
                    ret = ec2_client.describe_instance_status(InstanceIds=[each.id])
                    if len(ret.get('InstanceStatuses')) == 0:
                        print("watchdog: scaling in succeeds...")
                        break
                    if ret.get('InstanceStatuses')[0]['InstanceState']['Name'] == "terminated":
                        print("watchdog: scaling in succeeds...")
                        break
                    time.sleep(3)
                break


def drop_to_one():
    print("watchdog: scaling in ...")
    instance_lists = ec2_resource.instances.filter(Filters=(
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'tag:Name', 'Values': [service_identity]}
        ))
    for each in instance_lists:
        if each.id != service_instance_id and each.id != client_instance_id and each.id != watchdog_instance_id:
            each.terminate()


def get_queue_attribute():
    _response = sqs_client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
    )
    _num_msg_visible = _response.get('Attributes').get('ApproximateNumberOfMessages')
    _num_msg_invisible = _response.get('Attributes').get('ApproximateNumberOfMessagesNotVisible')
    return _num_msg_visible, _num_msg_invisible


def check_atleast_one():
    # ensure there should be at least one service instance active at all times
    reservations = ec2_client.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': [service_identity]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )
    mark = 0
    for reservation in reservations['Reservations']:
        service_instances = reservation['Instances']
        mark = 0
        for inst in service_instances:
            instance_id = inst['InstanceId']
            resp = ec2_client.describe_instance_status(InstanceIds=[instance_id])
            mark = 0
            for status in resp.get('InstanceStatuses'):
                if status['InstanceState']['Name'] != "running":
                    mark = 0
                    break
                if status['SystemStatus']['Status'] != "ok":
                    mark = 0
                    break
                if status['SystemStatus']['Details'][0]['Status'] != 'passed':
                    mark = 0
                    break
                if status['InstanceStatus']['Details'][0]['Status'] != 'passed':
                    mark = 0
                    break
                mark = 1
            if mark == 0:
                continue
            else:
                break
    if mark == 0:
        print("watchdog: no active service node ... fixing...")
        scale_out(1, True)
        print("watchdog: done.")
        exit(0)


def fault_detect(average_cpu_list):
    print("watchdog: fault detecting...")
    time.sleep(30)
    [_, _, _, _, new_average_cpu_list] = get_services_cpu_utilisation_metrics()
    for tu in average_cpu_list:
        for new_tu in new_average_cpu_list:
            if tu[0] != new_tu[0]:
                continue
            if tu[1] <= 0.85 and (new_tu[1] - tu[1] < 0.5):
                ec2_resource.Instance(tu[0]).terminate()
                print("watchdog: {} should be fault ... terminated".format(tu[0]))
                if tu[0] == service_instance_id:
                    scale_out(1, True)
                    print("watchdog: replace regular service node ... scale out done")
    print("watchdog: done.")


# ------------------------------  WORK-STATUS  ------------------------------
if option == "--status":
    # ec2 instances & CPUUtilization
    if option == "--status":
        print("--------------  Status Result -------------------")
    get_services_cpu_utilisation_metrics(option)
    # sqs queue
    response = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=['ApproximateNumberOfMessages'])
    queue_length = response.get('Attributes').get('ApproximateNumberOfMessages')
    print("queue length: <{}>".format(queue_length))
    if option == "--status":
        print("------------------   End   -------------------")


# ------------------------------     SCALE&FAULT     ------------------------------
if option == "--status":
    exit(0)

print("watchdog: analysing ... ")

check_atleast_one()

# _, _, _, _, average_cpu_list = get_services_cpu_utilisation_metrics()
# fault_detect(average_cpu_list)

num_msg_visible, num_msg_invisible = get_queue_attribute()

print("watchdog: observe visible and invisible msgs, {} and {} respectively".format(num_msg_visible, num_msg_invisible))
if int(num_msg_visible) > 0:
    # _, _, _, aggregate_max_cpu_u, _ = get_services_cpu_utilisation_metrics()
    scale_out(1)
    # flag = 0
    # if aggregate_max_cpu_u > 55:
    #     print("watchdog: cpu utilisation maintains at a high level over 55%. "
    #           "To increase a service node.")
    #     scale_out(1)
    # elif 1 < aggregate_max_cpu_u < 45:
    #     print("watchdog: cpu utilisation maintains at a low level below 45%. "
    #           "To maintain or decrease one service node.")
    #     scale_in(1)
    # elif 45 <= aggregate_max_cpu_u <= 55:
    #     print("watchdog: cpu utilisation maintains at around 50%. No actions.")
    # else:
    #     pass
elif int(num_msg_invisible) > 0:
    print("watchdog: there are still messages being processed, no scale in/out.")
else:
    _, min_points, counter, _, _ = get_services_cpu_utilisation_metrics()
    for m in min_points:
        if m[2] >= 2:
            print("watchdog: there is a service", m[0],
                  "that has over 2% of CPUUtilization; therefore, system could not be considered idle. No actions.")
            print("watchdog: done.")
            exit(0)
    if counter == 1:
        print("watchdog: system is being idle with only one service node. No actions.")
    else:
        print("watchdog: system should be idle. Shut down service nodes.")
        drop_to_one()
        print('watchdog: all idle service nodes have been terminated except regular one.')

print("watchdog: done.")

'''
aws cloudwatch get-metric-statistics --metric-name CPUUtilization --start-time 2017-05-17T08:40:00 --end-time 2017-05-17T08:45:00 --period 60 --namespace AWS/EC2 --statistics Maximum Average --dimensions Name=InstanceId,Value=i-02067ba4259f9bb2d
'''
