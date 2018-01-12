#!/usr/bin/python3
import boto3
import os, configparser, shutil, time

lock_file = 'request.lock'
lock_key = 1
unlock_key = -1


def process_request(req):
    # {'folder_name': 'simple_pics_76caa_2017-05-14-04-12-44',
    #  'bucket_input_name': 'unsw.9243.input.37214162-6574-4a46-9248-f1fad925a06d',
    #  'bucket_output_name': 'unsw.9243.output.cbcd1796-1461-4011-a1d9-ea6c39df15fe'}
    dictionary = {}
    elements = req.split("?")
    action = elements[0]
    paras = elements[1]
    if action == "transform":
        paras_list = paras.split(":")
        for para in paras_list:
            para_list = para.split("=")
            dictionary[para_list[0]] = para_list[1]
    return dictionary


def mutex(key):
    if key > 0:
        open(lock_file, 'a').close()
    else:
        os.remove(lock_file)


def is_processing():
    return os.path.exists(lock_file)


if is_processing():
    print('service: previous request is still under process')
    time.sleep(2)
    raise SystemExit


config = configparser.ConfigParser()
config.read("configure.ini")
region_name = config["INIT"]["region_name"]
aws_access_key = config["INIT"]["aws_access_key"]
aws_secret_access_key = config["INIT"]["aws_secret_access_key"]
queue_url = config["SQS"]["queue_url"]
video_format = ".mp4"


# ------------------------------   SESSION   ------------------------------
boto3.setup_default_session(
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name)
session = boto3.DEFAULT_SESSION
sqs_client = session.client(service_name='sqs')
sqs_resource = session.resource(service_name='sqs')
s3_client = session.client(service_name='s3')
s3_resource = session.resource(service_name='s3')


# ------------------------------    WORK   ------------------------------
queue = sqs_resource.Queue(queue_url)
for message in queue.receive_messages(MaxNumberOfMessages=1):
    print("service: processing a message")
    mutex(lock_key)
    request = message.body
    d = process_request(request)
    folder_name = d['folder_name']
    output_file = folder_name + video_format
    bucket_input_name = d['bucket_input_name']
    bucket_output_name = d['bucket_output_name']
    shutil.rmtree(folder_name, ignore_errors=True)
    os.mkdir(folder_name)
    bucket_input = s3_resource.Bucket(bucket_input_name)
    for element in bucket_input.objects.all():
        if not element.key.startswith(folder_name):
            continue
        s3_client.download_file(bucket_input_name, element.key, element.key)
    os.system('./minimoto_i2v ' + folder_name + ' ' + output_file)
    s3_client.upload_file(output_file, bucket_output_name, output_file)
    message.delete()
    mutex(unlock_key)
    print('service: video can be obtained in s3://' + bucket_output_name + '/' + output_file)
    os.system("rm -rf " + output_file)
    os.system("rm -rf " + folder_name)
