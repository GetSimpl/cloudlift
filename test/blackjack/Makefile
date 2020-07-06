SHELL=/bin/bash

build:
	docker build -t blackjack .

start:
	docker run -it --rm --init --name blackjack -p 1025:1025/udp -p 1026:1026/tcp blackjack

test:
	echo "deal" | socat - udp:localhost:1025
	echo "game" | socat - tcp:localhost:1026
	socat /dev/null TCP:localhost:1026

stop:
	docker stop blackjack
