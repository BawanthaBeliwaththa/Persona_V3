OS := $(shell uname)

up:
ifeq ($(OS), Linux)
	xhost +local:docker
	docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d
else ifeq ($(OS), Darwin)
	xhost +localhost
	docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d
endif

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
ifeq ($(OS), Linux)
	docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build
else ifeq ($(OS), Darwin)
	docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d --build
endif