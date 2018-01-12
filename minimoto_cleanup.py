#!/usr/bin/python3
import boto3, botocore
import boto.ec2
import configparser
import time

config = configparser.ConfigParser()
config.read("configure.ini")
my_dict = {}
for section in config.sections():
    items = config.items(section)
    for item in items:
        if item is not None:
            my_dict[item[0].upper()] = item[1]

key_file_name = my_dict.get('KEY_FILE_NAME')
aws_access_key = my_dict.get('AWS_ACCESS_KEY')
aws_secret_access_key = my_dict.get('AWS_SECRET_ACCESS_KEY')
region_name = my_dict.get('REGION_NAME')
sg_name = my_dict.get('SG_NAME')
bucket_input_name = my_dict.get('BUCKET_INPUT')
bucket_output_name = my_dict.get('BUCKET_OUTPUT')
queue_name = config['SQS']['QUEUE_NAME']
client_identity = config['EC2']['CLIENT_IDENTITY']
service_identity = config['EC2']['SERVICE_IDENTITY']
watchdog_identity = config['EC2']['WATCHDOG_IDENTITY']
image_name = config['AMI']['IMAGE_NAME']

# ------------------------------   SESSION   ------------------------------
boto3.setup_default_session(
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name)
session = boto3.DEFAULT_SESSION

sqs_resource = session.resource(service_name="sqs")
sqs_client = session.client(service_name="sqs")
s3_resource = session.resource(service_name='s3')
s3_client = session.client(service_name='s3')
ec2_resource = session.resource(service_name='ec2')
ec2_client = session.client(service_name='ec2')

# ------------------------------     SQS     ------------------------------
if queue_name is not None:
    print("cleanup: delete queue")
    try:
        response = sqs_client.create_queue(QueueName=queue_name)
        queue_url = response['QueueUrl']
        queue = sqs_resource.Queue(queue_url)
        queue.purge()
        queue.delete()
        print("cleanup: done.")
    except botocore.exceptions.ClientError as err:
        print("cleanup: {} doesn't exist".format(queue_name))

# ------------------------------     S3      ------------------------------
if bucket_input_name is not None:
    print("cleanup: delete bucket_input")
    try:
        s3_client.head_bucket(Bucket=bucket_input_name)
        bucket_input = s3_resource.Bucket(bucket_input_name)
        for key in bucket_input.objects.all():
            key.delete()
        response = bucket_input.delete()
        print("cleanup: done.")
    except botocore.exceptions.ClientError as err:
        print("cleanup: {} doesn't exist".format(bucket_input_name))

if bucket_output_name is not None:
    print("cleanup: delete bucket_output")
    try:
        s3_client.head_bucket(Bucket=bucket_output_name)
        bucket_output = s3_resource.Bucket(bucket_output_name)
        for key in bucket_output.objects.all():
            key.delete()
        response = bucket_output.delete()
        print("cleanup: done.")
    except botocore.exceptions.ClientError as err:
        print("cleanup: {} doesn't exist".format(bucket_output_name))

# ------------------------------     EC2     ------------------------------
terminated_instances = []
print("cleanup: waiting for ec2 instances terminating")
if client_identity is not None:
    reservations = ec2_client.describe_instances(
        Filters=[{'Name': 'tag:Name', 'Values': [client_identity]}]
    )
    for reservation in reservations['Reservations']:
        client_instances = reservation['Instances']
        for inst in client_instances:
            client_instance_id = inst['InstanceId']
            client_instance = ec2_resource.Instance(client_instance_id)
            client_instance.terminate()
            terminated_instances.append((client_instance, "client_instance"))

if watchdog_identity is not None:
    reservations = ec2_client.describe_instances(
        Filters=[{'Name': 'tag:Name', 'Values': [watchdog_identity]}]
    )
    for reservation in reservations['Reservations']:
        watchdog_instances = reservation['Instances']
        for inst in watchdog_instances:
            watchdog_instance_id = inst['InstanceId']
            watchdog_instance = ec2_resource.Instance(watchdog_instance_id)
            watchdog_instance.terminate()
            terminated_instances.append((watchdog_instance, "watchdog_instance"))

if service_identity is not None:
    reservations = ec2_client.describe_instances(
        Filters=[
            {'Name': 'instance-state-name', 'Values': ['running', 'pending', 'stopping', 'stopped']},
            {'Name': 'tag:Name', 'Values': [service_identity]}
        ]
    )
    for reservation in reservations['Reservations']:
        service_instances = reservation['Instances']
        for instance in service_instances:
            instance_id = instance['InstanceId']
            service_instance = ec2_resource.Instance(instance_id)
            service_instance.terminate()
            terminated_instances.append((service_instance, "service_instance"))

while True:
    deleted = []
    for instance in terminated_instances:
        if instance[0].state.get('Name') == "terminated":
            deleted.append(instance)
        else:
            instance[0].reload()
    for instance in deleted:
        print("cleanup: " + instance[1] + " terminated.")
        terminated_instances.remove(instance)
    if len(terminated_instances) == 0:
        break
    time.sleep(2)
print("cleanup: ec2 instances, all done.")

# ----------------------------- SECURITY GROUP ----------------------------
if sg_name is not None:
    try:
        print("cleanup: delete security group")
        security_group = ec2_client.delete_security_group(GroupName=sg_name)
        print("cleanup: done.")
    except botocore.exceptions.ClientError:
        print("cleanup: {} doesn't exist".format(sg_name))

# ------------------------------     AMI     ------------------------------
if image_name is not None:
    try:
        ec2_conn = boto.ec2.connect_to_region(
            region_name,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_access_key
        )
        print("cleanup: delete image")
        images = ec2_conn.get_all_images(filters={'name': image_name})
        if len(images) != 0:
            image = images[0]
            try:
                image.deregister(delete_snapshot=True)
            except:
                pass
            print("cleanup: done.")
        else:
            print("cleanup: {} doesn't exist".format(image_name))
    except botocore.exceptions.ClientError as err:
        print("cleanup: {} doesn't exist".format(image_name))