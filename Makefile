CLOUDSDK_PYTHON ?= /usr/local/opt/python@3.11/bin/python3.11
GCLOUD ?= $(HOME)/google-cloud-sdk/bin/gcloud

deploy:
	git pull origin nicegui-migration
	$(GCLOUD) builds submit --tag gcr.io/math-finance-simulator/app
	$(GCLOUD) run deploy math-finance-simulator --image gcr.io/math-finance-simulator/app --platform managed --region us-east1 --allow-unauthenticated --memory 512Mi --timeout 300

.PHONY: deploy
