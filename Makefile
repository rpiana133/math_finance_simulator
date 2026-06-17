deploy:
	git pull origin nicegui-migration
	gcloud builds submit --tag gcr.io/math-finance-simulator/app
	gcloud run deploy math-finance-simulator --image gcr.io/math-finance-simulator/app --platform managed --region us-east1 --allow-unauthenticated --memory 512Mi --timeout 300

.PHONY: deploy
