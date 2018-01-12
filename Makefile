all: run

run:
	sudo apt-get update > /dev/null
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pip  > /dev/null
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python-pip  > /dev/null
	sudo pip3 install boto3  > /dev/null
	sudo pip3 install boto  > /dev/null
	sudo chmod +x minimoto_setup.py minimoto_setup minimoto_cleanup.py minimoto_cleanup minimoto_client minimoto_service.py minimoto_watchdog.py minimoto_i2v minimoto_install minimoto_watchdog run_service