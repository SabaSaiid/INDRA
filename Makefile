# ==============================================================================
# INDRA Platform Developer Makefile
# Intelligent National Disaster & Weather Platform
# Smart India Hackathon 2026 - Problem Statement: SIH26069 | Team: Sixth Sense
# ==============================================================================

.DEFAULT_GOAL := help
.PHONY: help dev start bg stop restart status setup infra-up infra-down infra-status doctor demo test logs clean

help:
	@./start.sh help

setup:
	@./start.sh setup

dev:
	@./start.sh start

start:
	@./start.sh start

bg:
	@./start.sh bg

stop:
	@./start.sh stop

restart:
	@./start.sh restart

status:
	@./start.sh status

infra-up:
	@./start.sh infra up

infra-down:
	@./start.sh infra down

infra-status:
	@./start.sh infra ps

infra-ps:
	@./start.sh infra ps

doctor:
	@./start.sh doctor

demo:
	@./start.sh demo

test:
	@./start.sh test

logs:
	@./start.sh logs

clean:
	@./start.sh clean
