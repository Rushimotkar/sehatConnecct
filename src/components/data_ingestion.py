"""
Data Ingestion Component

raw data -> read -> validate -> train test split ->
save -> return file paths
"""

import os
import sys
import pandas as pd
from dataclasses import dataclass
from sklearn.model_selection import train_test_split

from src.exception import CustomException
from src.logger import logging

from src.components.data_transformation import DataTransformation
from src.components.model_trainer import ModelTrainer
from src.pipeline.prediction_pipeline import CustomData, PredictPipeline


# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
@dataclass
class DataIngestionConfig:
    train_data_path: str = os.path.join('artifacts', 'train.csv')
    test_data_path: str = os.path.join('artifacts', 'test.csv')
    raw_data_path: str = os.path.join('artifacts', 'data.csv')


# ─────────────────────────────────────────
# DATA INGESTION
# ─────────────────────────────────────────
class DataIngestion:
    def __init__(self):
        self.ingestion_config = DataIngestionConfig()

    def initiate_data_ingestion(self):
        logging.info('Entered data ingestion')

        try:
            df = pd.read_csv(
                r'C:\Users\hp\OneDrive\Attachments\Desktop\medico\notebook\data\cleaned.csv'
            )

            logging.info('Dataset loaded')

            os.makedirs(
                os.path.dirname(self.ingestion_config.train_data_path),
                exist_ok=True
            )

            # Save raw data
            df.to_csv(self.ingestion_config.raw_data_path, index=False)

            # Train-test split
            train_set, test_set = train_test_split(
                df, test_size=0.2, random_state=42
            )

            train_set.to_csv(self.ingestion_config.train_data_path, index=False)
            test_set.to_csv(self.ingestion_config.test_data_path, index=False)

            logging.info('Data ingestion completed')

            return (
                self.ingestion_config.train_data_path,
                self.ingestion_config.test_data_path
            )

        except Exception as e:
            raise CustomException(e, sys)


# ─────────────────────────────────────────
# MAIN PIPELINE EXECUTION
# ─────────────────────────────────────────
if __name__ == "__main__":

    try:
        # ── Stage 1: Data Ingestion ──
        ingestion = DataIngestion()
        train_path, test_path = ingestion.initiate_data_ingestion()

        # ── Stage 2: Data Transformation ──
        data_transformation = DataTransformation()
        train_arr, test_arr, preprocessor_path = data_transformation.initiate_data_transformation(
            train_path, test_path
        )

        # ── Stage 3: Model Training ──
        trainer = ModelTrainer()
        accuracy, best_model = trainer.initiate_model_training(
            train_arr, test_arr
        )

        print(f"\n Best model: {best_model}")
        print(f" Accuracy  : {accuracy:.4f}")

        # ── Stage 4: Prediction ──
        data = CustomData(
            symptoms="fever and cough",
            age_group="Adult",
            severity="Mild",
            allergies="None"
        )

        df = data.get_data_as_dataframe()

        pipeline = PredictPipeline()
        result = pipeline.predict(df)

        details = pipeline.get_medicine_details(result["medicine"])

        # ── Final Output ──
        print("\n" + "=" * 45)
        print("        MEDIGUIDE PREDICTION RESULT")
        print("=" * 45)
        print(f" Medicine   : {result['medicine']}")
        print(f" Specialty  : {result['specialty']}")
        print(f" Confidence : {result['confidence']}%")
        print("-" * 45)
        print(f" Dosage     : {details['dosage']}")
        print(f" Frequency  : {details['frequency']}")
        print(f" Type       : {details['type']}")
        print(f" Warning    : {details['warning']}")
        print("=" * 45)

    except Exception as e:
        raise CustomException(e, sys)