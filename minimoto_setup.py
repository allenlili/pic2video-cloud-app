#!/usr/bin/python3
import boto3
import configparser
import uuid
import time
import os
import sys

# aws_access_key_id = AKIAJNLCC5A6KTOS6D5A
# aws_secret_access_key = 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
# aws_access_key_id = AKIAID2QG2KUOLRV2Q7Q
# aws_secret_access_key = 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
# ./minimoto_setup.sh MySetupKeyPair.pem AKIAJNLCC5A6KTOS6D5A Vu2YlQzIZY2vUq+IJ1RiCFboahuTco3pe/W6tSFh
# ./minimoto_setup.sh MySetupKeyPair.pem AKIAID2QG2KUOLRV2Q7Q iSQJZTCFlAvEEkN9O6FYlhNVzlWBOwp+9N3NkiCe


def write_config(handle):
    config_file = open('configure.ini', 'w')
    handle.write(config_file)
    config_file.close()
    handle = configparser.ConfigParser()
    handle.read("configure.ini")
    return handle

DEBUG = True
config = configparser.ConfigParser()
config['INIT'] = {}
config['SQS'] = {}
config['S3'] = {}
config['EC2'] = {}
config['SECURITY_GROUP'] = {}
config['AMI'] = {}
config['OUTPUT'] = {}
config = write_config(config)

key_file = sys.argv[1:][0]
key_file_name = key_file.split(".")[0]
aws_access_key = sys.argv[1:][1]
aws_secret_access_key = sys.argv[1:][2]

# key_file = "MySetupKeyPair.pem"
# key_file_name = key_file.split(".")[0]
# aws_access_key = "AKIAID2QG2KUOLRV2Q7Q"
# aws_secret_access_key = "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"

region_name = "ap-southeast-2"
config['INIT']['KEY_FILE'] = key_file
config['INIT']['KEY_FILE_NAME'] = key_file_name
config['INIT']['REGION_NAME'] = region_name
config['INIT']['AWS_ACCESS_KEY'] = aws_access_key
config['INIT']['AWS_SECRET_ACCESS_KEY'] = aws_secret_access_key
config['INIT']['SERVICE_EC2_TYPE'] = "t2.xlarge"
service_ec2_type = config['INIT']['SERVICE_EC2_TYPE']
sg_name = 'sg_assn3_' + uuid.uuid4().__str__()[0:5]
sg_desc = 'my security group'
queue_name = 'myQueue_' + uuid.uuid4().__str__()[0:5]
bucket_input_name = "9243input.q." + uuid.uuid4().__str__()
bucket_output_name = "9243output.q." + uuid.uuid4().__str__()
ec2_identity = "_" + uuid.uuid4().__str__()
ami_id = "ami-96666ff5"
image_name = 'ami_' + uuid.uuid4().__str__()[0:5]
visible_time = '630'
configfile = "configure.ini"
config['SECURITY_GROUP']['SG_NAME'] = sg_name
config['SQS']['QUEUE_NAME'] = queue_name
config['SQS']['VISIBLE_TIME'] = visible_time
config['S3']['BUCKET_INPUT'] = bucket_input_name
config['S3']['BUCKET_OUTPUT'] = bucket_output_name
config['EC2']['CLIENT_IDENTITY'] = "client" + ec2_identity
config['EC2']['SERVICE_IDENTITY'] = "service" + ec2_identity
config['EC2']['WATCHDOG_IDENTITY'] = "watchdog" + ec2_identity
config['AMI']['IMAGE_NAME'] = image_name
config = write_config(config)

# ------------------------------   SESSION   ------------------------------
boto3.setup_default_session(
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name)
session = boto3.DEFAULT_SESSION

ec2_client = session.client(service_name="ec2")
ec2_resource = session.resource(service_name="ec2")
sqs = session.resource(service_name='sqs')
s3 = session.resource(service_name='s3')

try:
    # ----------------------------- SECURITY GROUP ----------------------------
    if DEBUG:
        print('setup: waiting for security group ')
    security_group = ec2_client.create_security_group(GroupName=sg_name, Description=sg_desc)
    sg_id = security_group.get('GroupId')
    ec2_client.authorize_security_group_ingress(GroupId=sg_id, IpProtocol="-1", CidrIp='0.0.0.0/0')
    if DEBUG:
        print('setup: done.')
    config['SECURITY_GROUP']['SECURITY_GROUP_ID'] = sg_id
    config = write_config(config)

    # ------------------------------     SQS     ------------------------------
    if DEBUG:
        print('setup: waiting for queue instance ')
    queue = sqs.create_queue(QueueName=queue_name, Attributes={'VisibilityTimeout': visible_time})
    queue_url = queue.url
    while queue_url is None:
        time.sleep(3)
        queue.reload()
        queue_url = queue.url
    if DEBUG:
        print('setup: done.')
    config['SQS']['QUEUE_URL'] = queue_url
    config = write_config(config)

    # ------------------------------     S3      ------------------------------
    if DEBUG:
        print('setup: waiting for bucket instances ')
    config['OUTPUT']['S3_BUCKET_INPUT'] = bucket_input_name
    config['OUTPUT']['S3_BUCKET_OUTPUT'] = bucket_output_name

    bucket_input = s3.create_bucket(
        Bucket=bucket_input_name,
        CreateBucketConfiguration={'LocationConstraint': 'ap-southeast-2'}
    )
    bucket_output = s3.create_bucket(
        Bucket=bucket_output_name,
        CreateBucketConfiguration={'LocationConstraint': 'ap-southeast-2'}
    )
    while bucket_input.creation_date is None or bucket_output.creation_date is None:
        time.sleep(3)
        bucket_input.load()
        bucket_output.load()
    if DEBUG:
        print('setup: done.')
    config = write_config(config)

    # ------------------------------     EC2     ------------------------------
    if DEBUG:
        print('setup: waiting for ec2 client/watchdong/service instances')
    started_instances = []

    # client instance
    instances = ec2_resource.create_instances(
        ImageId=ami_id, MinCount=1, MaxCount=1, KeyName=key_file_name,
        SecurityGroupIds=[sg_id], InstanceType="t2.micro",
        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'client' + ec2_identity}]}]
    )
    if instances[0] is not None:
        started_instances.append((instances[0], "CLIENT"))

    # watchdog instance
    instances = ec2_resource.create_instances(
        ImageId=ami_id, MinCount=1, MaxCount=1, KeyName=key_file_name,
        SecurityGroupIds=[sg_id], InstanceType="t2.micro",
        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'watchdog' + ec2_identity}]}]
    )
    if instances[0] is not None:
        started_instances.append((instances[0], "WATCHDOG"))

    # trans-coding service
    instances = ec2_resource.create_instances(
        ImageId=ami_id, MinCount=1, MaxCount=1, KeyName=key_file_name,
        SecurityGroupIds=[sg_id], InstanceType=service_ec2_type, Monitoring={'Enabled': True},
        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': 'service' + ec2_identity}]}]
    )
    if instances[0] is not None:
        started_instances.append((instances[0], "SERVICE"))

    # ec2 instances state running
    client_instance_id, watchdog_instance_id, service_instance_id = None, None, None
    while True:
        running = []
        for instance in started_instances:
            if instance[0].state.get('Name') == "running":
                running.append(instance)
            else:
                instance[0].reload()
        for instance in running:
            if instance[1] == "CLIENT":
                client_instance_id = instance[0].instance_id
                config['EC2']['CLIENT_ID'] = client_instance_id
                config['OUTPUT']['CLIENT_USER'] = "ubuntu"
                config['OUTPUT']['CLIENT_ADDR'] = instance[0].public_dns_name
                config = write_config(config)
            if instance[1] == "WATCHDOG":
                watchdog_instance_id = instance[0].instance_id
                config['EC2']['WATCHDOG_ID'] = watchdog_instance_id
                config['OUTPUT']['WATCHDOG_USER'] = "ubuntu"
                config['OUTPUT']['WATCHDOG_ADDR'] = instance[0].public_dns_name
                config = write_config(config)
            if instance[1] == "SERVICE":
                service_instance_id = instance[0].instance_id
                config['EC2']['SERVICE_ID'] = service_instance_id
                config['OUTPUT']['SERVICE_USER'] = "ubuntu"
                config['OUTPUT']['SERVICE_ADDR'] = instance[0].public_dns_name
                config = write_config(config)
            started_instances.remove(instance)
        if len(started_instances) == 0:
            break
        time.sleep(2)

    while True:
        flag = 1
        response = ec2_client.describe_instance_status(
            InstanceIds=[client_instance_id, watchdog_instance_id, service_instance_id]
        )
        for status in response.get('InstanceStatuses'):
            if status['InstanceState']['Name'] != "running":
                flag = 0
            if status['SystemStatus']['Status'] != "ok":
                flag = 0
            if status['SystemStatus']['Details'][0]['Status'] != 'passed':
                flag = 0
            if status['InstanceStatus']['Details'][0]['Status'] != 'passed':
                flag = 0
        if flag == 1:
            if DEBUG:
                print("setup: all can be reached")
            break
        time.sleep(2)
    if DEBUG:
        print("setup: done.")

    # ------------------------------   INSTALL   ------------------------------
    print("setup: install code and softwares into instances...")
    key_file = key_file
    host = "ubuntu"

    client_addr = config['OUTPUT']['CLIENT_ADDR']
    client_host = host + "@" + client_addr
    client_code = "minimoto_client"

    watchdog_addr = config['OUTPUT']['WATCHDOG_ADDR']
    watchdog_host = host + "@" + watchdog_addr
    watchdog_code = "minimoto_watchdog.py"

    service_addr = config['OUTPUT']['SERVICE_ADDR']
    service_host = host + "@" + service_addr
    service_code = "minimoto_service.py"
    trans_code = "minimoto_i2v"
    install_command = ' '.join(
        [
            './minimoto_install',
            key_file, host,
            client_addr, client_code,
            watchdog_addr, watchdog_code,
            service_addr, service_code, trans_code, '> /dev/null'
        ]
    )
    os.system(install_command)

    def check_software_install():
        command = "dpkg-query -l 'python3' > /dev/null"
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))
        if resp != 0:
            print("setup: python3 not installed")
            return False

        command = "dpkg-query -l 'python' > /dev/null"
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))
        if resp != 0:
            print("setup: python not installed")
            return False

        command = "pip3 list | grep -F -w 'boto' > /dev/null"
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))
        if resp != 0:
            print("setup: python-boto not installed")
            return False

        command = "pip3 list | grep -F -w 'boto3' > /dev/null"
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))
        if resp != 0:
            print("setup: python-boto3 not installed")
            return False
        return True

    def check_client_install():
        rt = check_software_install()

        command = 'test -e {}'.format(client_code)
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))

        if resp != 0 or rt is False:
            return False
        print("setup: client code and softwares are installed.")
        return True


    def check_watchdog_install():
        rt = check_software_install()

        command = 'test -e {}'.format(watchdog_code)
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))
        command = 'test -e {}'.format(key_file)
        resp2 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))
        command = 'test -e {}'.format("minimoto_watchdog")
        resp3 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))

        if rt is False or resp != 0 or resp2 != 0 or resp3 != 0:
            return False

        print("setup: watchdog code and softwares are installed.")
        return True


    def check_service_install():
        rt = check_software_install()
        command = "dpkg-query -l {} > /dev/null".format("imagemagick")
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, service_host, command))
        command = "dpkg-query -l {} > /dev/null".format("libav-tools")
        resp2 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, service_host, command))

        command = 'test -e {}'.format("run_service")
        resp3 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, client_host, command))
        command = 'test -e {}'.format("service.cron")
        resp4 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))
        command = 'test -e {}'.format(service_code)
        resp5 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))
        command = 'test -e {}'.format(trans_code)
        resp6 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))
        command = 'test -e {}'.format("minimoto_service")
        resp7 = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, watchdog_host, command))

        if rt is False or resp != 0 or resp2 != 0 or resp3 != 0 or resp4 != 0 or resp5 != 0 or resp6 != 0 \
                or resp7 != 0:
            return False

        print("setup: service code and softwares are installed.")
        return True

    while check_client_install() and check_watchdog_install() and check_service_install():
        os.system(install_command)

    # ------------------------------     AMI     ------------------------------
    time.sleep(5)
    if DEBUG:
        print('setup: waiting for AMI ')
    response = ec2_client.create_image(
        InstanceId=service_instance_id,
        Name=image_name
    )
    service_ami = response.get("ImageId")
    image = ec2_resource.Image(service_ami)
    while image.state != "available":
        time.sleep(2)
        image.reload()
    if DEBUG:
        print('setup: done.')
    config['AMI']['SERVICE_AMI'] = service_ami
    config['OUTPUT']['SERVICE_AMI'] = service_ami
    config = write_config(config)

    # ------------------------------   OUTPUT    ------------------------------
    print("minimoto_setup: mandatory output messages follow")
    for key in config['OUTPUT']:
        if key == "SERVICE_ADDR".lower():
            continue
        print(key.upper(), "=", config['OUTPUT'][key], sep="")

    # ------------------------------ File TRANS  ------------------------------
    def configure_transfer(h):
        command = "scp -o StrictHostKeyChecking=no -i " + key_file + ' ' + configfile + ' ' + h + ':~'
        print(command)
        os.system(command)

    def check_configure_exist(h):
        command = 'test -e {}'.format(configfile)
        resp = os.system("ssh -o StrictHostKeyChecking=no -i {} {} {}".format(key_file, h, command))
        if resp != 0:
            return False
        return True

    configure_transfer(client_host)

    configure_transfer(watchdog_host)

    configure_transfer(service_host)

    while not check_configure_exist(client_host):
        configure_transfer(client_host)

    while not check_configure_exist(watchdog_host):
        configure_transfer(watchdog_host)

    while not check_configure_exist(service_host):
        configure_transfer(service_host)

except:
    time.sleep(8)
    script = "./minimoto_cleanup"
    os.system(script)
