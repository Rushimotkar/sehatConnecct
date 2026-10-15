import os
import sys
import numpy as np
import pandas as pd
import scipy.sparse as sp
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder

from src.logger import logging
from src.exception import CustomException
from src.utils.comman import save_object


# ── Config ────────────────────────────────────
@dataclass
class DataTransformationConfig:
    preprocessor_obj_path: str = os.path.join(
        "artifacts", "preprocessor.pkl"
    )


# ── Main Class ────────────────────────────────
class DataTransformation:
    def __init__(self):
        self.data_transformation_config = DataTransformationConfig()

    def initiate_data_transformation(self, train_path, test_path):
        try:
            logging.info(">>> Data Transformation Started")

            # ── STEP 1: Load Data ──────────────────────────
            train_df = pd.read_csv(train_path)
            test_df = pd.read_csv(test_path)

            logging.info(f"Train shape: {train_df.shape}")
            logging.info(f"Test  shape: {test_df.shape}")
            logging.info(f"Columns    : {list(train_df.columns)}")

            # ── STEP 2: Define Columns ─────────────────────
            text_column = "Symptoms"
            target_column = "Medicine"

            # ── STEP 3: Load Full Data (for label encoding) ───
            logging.info("Loading full dataset for label encoding...")

            full_df = pd.read_csv(
                "C:\\Users\\hp\\OneDrive\\Attachments\\Desktop\\medico\\notebook\\data\\cleaned.csv"
            )

            # ── STEP 4: Handle Missing Values ───────────────
            train_df[text_column].fillna("unknown", inplace=True)
            test_df[text_column].fillna("unknown", inplace=True)

            train_df[target_column].fillna("unknown", inplace=True)
            test_df[target_column].fillna("unknown", inplace=True)
            full_df[target_column]=full_df[target_column].fillna("unknown")

            # ── STEP 5: Split X and y ──────────────────────
            X_train = train_df[text_column].values
            y_train = train_df[target_column].values

            X_test = test_df[text_column].values
            y_test = test_df[target_column].values

            # ── STEP 6: TF-IDF ─────────────────────────────
            logging.info("Fitting TF-IDF Vectorizer...")

            tfidf = TfidfVectorizer(
                max_features=1500,
                ngram_range=(1, 2),
                stop_words="english",
                lowercase=True
            )

            X_train_tfidf = tfidf.fit_transform(X_train)
            X_test_tfidf = tfidf.transform(X_test)

            logging.info(f"TF-IDF train shape : {X_train_tfidf.shape}")
            logging.info(f"TF-IDF test  shape : {X_test_tfidf.shape}")
            logging.info(f"Vocabulary size    : {len(tfidf.vocabulary_)}")

            # ── STEP 7: Label Encoding ─────────────────────
            logging.info("Encoding target labels...")

            label_encoder = LabelEncoder()

            # Fit on full dataset (avoid unseen labels)
            all_labels = full_df[target_column].values
            label_encoder.fit(all_labels)

            y_train_enc = label_encoder.transform(y_train)
            y_test_enc = label_encoder.transform(y_test)

            logging.info(f"Total classes : {len(label_encoder.classes_)}")
            logging.info(f"Classes       : {list(label_encoder.classes_)}")

            # ── STEP 8: Combine Arrays ─────────────────────
            y_train_sparse = sp.csr_matrix(y_train_enc.reshape(-1, 1))
            y_test_sparse = sp.csr_matrix(y_test_enc.reshape(-1, 1))

            train_arr = sp.hstack([X_train_tfidf, y_train_sparse]).toarray()
            test_arr = sp.hstack([X_test_tfidf, y_test_sparse]).toarray()

            logging.info(f"Final train_arr : {train_arr.shape}")
            logging.info(f"Final test_arr  : {test_arr.shape}")

            # ── STEP 9: Save Preprocessor ──────────────────
            logging.info("Saving preprocessing object...")

            save_object(
                file_path=self.data_transformation_config.preprocessor_obj_path,
                obj={
                    "tfidf": tfidf,
                    "label_encoder": label_encoder
                }
            )

            logging.info(">>> Data Transformation Completed ")

            return train_arr, test_arr, self.data_transformation_config.preprocessor_obj_path

        except Exception as e:
            raise CustomException(e, sys)