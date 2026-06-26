CLOUDSDK_PYTHON ?= /usr/local/opt/python@3.11/bin/python3.11
GCLOUD ?= $(HOME)/google-cloud-sdk/bin/gcloud

push:
	git push origin HEAD

deploy:
	$(GCLOUD) builds submit --tag gcr.io/math-finance-simulator/app
	$(GCLOUD) run deploy math-finance-simulator \
		--image gcr.io/math-finance-simulator/app \
		--region us-east1 --allow-unauthenticated \
		--session-affinity --timeout=600 --memory=512Mi \
		--set-env-vars=FINNHUB_API_KEY=d8p8qkpr01qp954vuvfgd8p8qkpr01qp954vuvg0,TEACHER_EMAILS=rpiana@stjohnsguam.com,GOOGLE_HD=stjohnsguam.com,REDIRECT_URI=https://math-finance-simulator-743218768808.us-east1.run.app/callback \
		--set-secrets=STORAGE_SECRET=STORAGE_SECRET:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,GCS_SERVICE_ACCOUNT=GCS_SERVICE_ACCOUNT:latest,BLOB_KEY_SECRET=BLOB_KEY_SECRET:latest

.PHONY: push deploy
