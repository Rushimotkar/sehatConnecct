import os
import sys
import pandas as pd
from dataclasses import dataclass

from src.logger import logging
from src.exception import CustomException
from src.utils.comman import load_object


# ── Config ────────────────────────────────────
@dataclass
class PredictPipelineConfig:
    model_path:        str = os.path.join("artifacts", "model.pkl")
    preprocessor_path: str = os.path.join("artifacts", "preprocessor.pkl")


# ── Custom Data ───────────────────────────────
class CustomData:
    def __init__(
        self,
        symptoms:  str,
        age_group: str,
        severity:  str,
        allergies: str
    ):
        self.symptoms  = symptoms
        self.age_group = age_group
        self.severity  = severity
        self.allergies = allergies

    def get_data_as_dataframe(self):
        try:
            data = {
                "symptoms" : [self.symptoms],
                "age_group": [self.age_group],
                "severity" : [self.severity],
                "allergies": [self.allergies]
            }
            df = pd.DataFrame(data)
            logging.info(f"Input DataFrame:\n{df}")
            return df
        except Exception as e:
            raise CustomException(e, sys)


# ── Predict Pipeline ──────────────────────────
class PredictPipeline:
    def __init__(self):
        self.config = PredictPipelineConfig()

    # ─────────────────────────────────────────
    def predict(self, features: pd.DataFrame):
        try:
            logging.info(">>> Predict Pipeline Started")

            # Check files exist
            if not os.path.exists(self.config.model_path):
                raise CustomException(
                    "model.pkl not found! Train first.", sys
                )
            if not os.path.exists(self.config.preprocessor_path):
                raise CustomException(
                    "preprocessor.pkl not found! Train first.", sys
                )

            # Load preprocessor
            logging.info("Loading preprocessor...")
            preprocessor_bundle = load_object(
                self.config.preprocessor_path
            )
            tfidf         = preprocessor_bundle["tfidf"]
            label_encoder = preprocessor_bundle["label_encoder"]

            # Load model
            logging.info("Loading model...")
            model = load_object(self.config.model_path)

            # Transform input
            symptom_text  = features["symptoms"].values
            X_transformed = tfidf.transform(symptom_text)

            logging.info(f"Input   : {symptom_text}")
            logging.info(f"Shape   : {X_transformed.shape}")

            # Predict
            prediction_enc = model.predict(X_transformed)
            logging.info(f"Raw pred: {prediction_enc}")
            logging.info(f"dtype   : {prediction_enc.dtype}")

            # Confidence
            if hasattr(model, "predict_proba"):
                proba      = model.predict_proba(X_transformed)
                confidence = round(max(proba[0]) * 100, 2)
            else:
                confidence = None

            # Decode — cast float64 → int
            predicted_medicine = label_encoder.inverse_transform(
                prediction_enc.astype(int)
            )[0]

            # Get specialty ← calls method inside same class
            specialty = self.get_specialty(
                features["symptoms"].values[0]
            )

            logging.info(f"Medicine  : {predicted_medicine}")
            logging.info(f"Specialty : {specialty}")
            logging.info(f"Confidence: {confidence}%")
            logging.info(">>> Predict Pipeline Completed ✅")

            return {
                "medicine"  : predicted_medicine,
                "specialty" : specialty,
                "confidence": confidence
            }

        except Exception as e:
            raise CustomException(e, sys)

    # ─────────────────────────────────────────
    def get_specialty(self, symptom: str) -> str:
        """
        ✅ This method is INSIDE PredictPipeline class
        Indented with 4 spaces under class
        """
        symptom = symptom.lower()

        specialty_map = {
            "chest pain" : "Cardiologist",
            "heart"      : "Cardiologist",
            "cough"      : "Pulmonologist",
            "breathing"  : "Pulmonologist",
            "skin"       : "Dermatologist",
            "rash"       : "Dermatologist",
            "headache"   : "Neurologist",
            "migraine"   : "Neurologist",
            "diabetes"   : "Endocrinologist",
            "sugar"      : "Endocrinologist",
            "eye"        : "Ophthalmologist",
            "vision"     : "Ophthalmologist",
            "back pain"  : "Orthopedic",
            "joint"      : "Orthopedic",
            "anxiety"    : "Psychiatrist",
            "depression" : "Psychiatrist",
            "fever"      : "General Physician",
            "cold"       : "General Physician",
            "stomach"    : "Gastroenterologist",
            "digestion"  : "Gastroenterologist",
        }

        for keyword, spec in specialty_map.items():
            if keyword in symptom:
                return spec

        return "General Physician"

    # ─────────────────────────────────────────
    def get_medicine_details(self, medicine: str) -> dict:
        """
         Also INSIDE PredictPipeline class
        """
        medicine_db = {
            "Paracetamol": {
                "dosage"   : "500mg",
                "frequency": "Every 6 hours",
                "warning"  : "Max 4g/day. Avoid alcohol.",
                "type"     : "Analgesic"
            },
            "Ibuprofen": {
                "dosage"   : "400mg",
                "frequency": "Every 8 hours",
                "warning"  : "Take with food.",
                "type"     : "NSAID"
            },
            "Amoxicillin": {
                "dosage"   : "500mg",
                "frequency": "Every 8 hours",
                "warning"  : "Complete full course.",
                "type"     : "Antibiotic"
            },
            "Metformin": {
                "dosage"   : "500mg",
                "frequency": "Twice daily with meals",
                "warning"  : "Monitor blood sugar.",
                "type"     : "Antidiabetic"
            },
            "Cetirizine": {
                "dosage"   : "10mg",
                "frequency": "Once daily",
                "warning"  : "May cause drowsiness.",
                "type"     : "Antihistamine"
            },
        }

        return medicine_db.get(medicine, {
            "dosage"   : "As prescribed",
            "frequency": "As prescribed",
            "warning"  : "Consult your doctor.",
            "type"     : "Unknown"
        })