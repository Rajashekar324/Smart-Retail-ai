from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
import logging
import pickle
import hashlib
from functools import lru_cache
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Import numpy first to avoid dependency issues with pandas
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.models import Order, OrderItem, Product


class DataPreprocessor:
    """Handles data preprocessing for time series forecasting"""
    
    @staticmethod
    def handle_missing_dates(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fill missing dates with interpolated values"""
        if not data:
            return data
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # Create complete date range
        date_range = pd.date_range(
            start=df['date'].min(),
            end=df['date'].max(),
            freq='D'
        )
        
        # Reindex to include all dates
        df = df.set_index('date').reindex(date_range)
        
        # Interpolate missing values
        df['revenue'] = df['revenue'].interpolate(method='linear').ffill().bfill()
        df['orders'] = df['orders'].interpolate(method='linear').ffill().bfill().fillna(0)
        
        # Convert back to list of dicts
        df = df.reset_index().rename(columns={'index': 'date'})
        return [
            {
                'date': row['date'].strftime('%Y-%m-%d'),
                'revenue': float(row['revenue']),
                'orders': int(row['orders'])
            }
            for _, row in df.iterrows()
        ]
    
    @staticmethod
    def remove_outliers(data: List[Dict[str, Any]], method: str = 'iqr') -> List[Dict[str, Any]]:
        """Remove outliers using IQR or z-score method"""
        if len(data) < 10:
            return data
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        
        if method == 'iqr':
            Q1 = df['revenue'].quantile(0.25)
            Q3 = df['revenue'].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            df = df[(df['revenue'] >= lower_bound) & (df['revenue'] <= upper_bound)]
        elif method == 'zscore':
            z_scores = np.abs((df['revenue'] - df['revenue'].mean()) / df['revenue'].std()).values
            df = df[z_scores < 3]
        
        return [
            {
                'date': row['date'],
                'revenue': float(row['revenue']),
                'orders': int(row['orders'])
            }
            for _, row in df.iterrows()
        ]
    
    @staticmethod
    def add_rolling_features(data: List[Dict[str, Any]], windows: List[int] = [7, 14, 30]) -> List[Dict[str, Any]]:
        """Add rolling average and rolling std features"""
        if len(data) < max(windows):
            return data
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        for window in windows:
            if len(df) >= window:
                df[f'rolling_avg_{window}'] = df['revenue'].rolling(window=window).mean()
                df[f'rolling_std_{window}'] = df['revenue'].rolling(window=window).std()
        
        # Fill NaN values
        df = df.bfill().ffill()

        return [
            {
                'date': row['date'].strftime('%Y-%m-%d'),
                'revenue': float(row['revenue']),
                'orders': int(row['orders']),
                **{k: float(v) if pd.notna(v) else 0.0 for k, v in row.items()
                   if k.startswith('rolling_')}
            }
            for _, row in df.iterrows()
        ]
    
    @staticmethod
    def add_lag_features(data: List[Dict[str, Any]], lags: List[int] = [1, 7, 14]) -> List[Dict[str, Any]]:
        """Add lag features for time series"""
        if len(data) < max(lags):
            return data
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        for lag in lags:
            if len(df) > lag:
                df[f'lag_{lag}'] = df['revenue'].shift(lag)
        
        # Fill NaN values
        df = df.bfill().ffill().fillna(0)

        return [
            {
                'date': row['date'].strftime('%Y-%m-%d'),
                'revenue': float(row['revenue']),
                'orders': int(row['orders']),
                **{k: float(v) if pd.notna(v) else 0.0 for k, v in row.items()
                   if k.startswith('lag_')}
            }
            for _, row in df.iterrows()
        ]
    
    @staticmethod
    def scale_data(data: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Any]:
        """Scale numerical features using MinMaxScaler"""
        import pandas as pd
        from sklearn.preprocessing import MinMaxScaler
        
        df = pd.DataFrame(data)
        
        scaler = MinMaxScaler()
        df['revenue_scaled'] = scaler.fit_transform(df[['revenue']])
        
        scaled_data = [
            {
                'date': row['date'],
                'revenue': float(row['revenue']),
                'revenue_scaled': float(row['revenue_scaled']),
                'orders': int(row['orders'])
            }
            for _, row in df.iterrows()
        ]
        
        return scaled_data, scaler


class ModelEvaluator:
    """Evaluates forecasting models using various metrics"""
    
    @staticmethod
    def calculate_metrics(actual: List[float], predicted: List[float]) -> Dict[str, float]:
        """Calculate evaluation metrics"""
        if len(actual) != len(predicted) or len(actual) == 0:
            return {}
        
        actual = np.array(actual)
        predicted = np.array(predicted)
        
        # MAE (Mean Absolute Error)
        mae = np.mean(np.abs(actual - predicted))
        
        # RMSE (Root Mean Square Error)
        rmse = np.sqrt(np.mean((actual - predicted) ** 2))
        
        # MAPE (Mean Absolute Percentage Error)
        mape = np.mean(np.abs((actual - predicted) / (actual + 1e-10))) * 100
        
        # R² Score
        ss_res = np.sum((actual - predicted) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        return {
            'mae': float(mae),
            'rmse': float(rmse),
            'mape': float(mape),
            'r2': float(r2)
        }
    
    @staticmethod
    def time_series_cv_split(data: List[Dict[str, Any]], n_splits: int = 5) -> List[Tuple[List, List]]:
        """Perform time series cross-validation split"""
        if len(data) < n_splits * 2:
            return []
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        df = df.sort_values('date')
        
        split_size = len(df) // (n_splits + 1)
        splits = []
        
        for i in range(n_splits):
            train_end = split_size * (i + 1)
            test_end = split_size * (i + 2)
            
            train = df.iloc[:train_end].to_dict('records')
            test = df.iloc[train_end:test_end].to_dict('records')
            
            splits.append((train, test))
        
        return splits


class DemandForecastingService:
    """Production-grade demand forecasting service with real ML models"""
    
    def __init__(self):
        self.models = {}
        self.preprocessor = DataPreprocessor()
        self.evaluator = ModelEvaluator()
        self.model_cache_dir = Path(__file__).parent.parent.parent / "model_cache"
        self.model_cache_dir.mkdir(exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=3)
        
        # Minimum data requirements
        self.MIN_DATA_POINTS_PROPHET = 30
        self.MIN_DATA_POINTS_ARIMA = 20
        self.MIN_DATA_POINTS_LSTM = 50
    
    def _get_cache_key(self, data_hash: str, model_type: str) -> str:
        """Generate cache key for model"""
        return f"{model_type}_{data_hash}"
    
    def _compute_data_hash(self, data: List[Dict[str, Any]]) -> str:
        """Compute hash of data for caching"""
        import hashlib
        import json
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(data_str.encode()).hexdigest()
    
    def _save_model(self, model: Any, cache_key: str):
        """Save model to cache"""
        cache_path = self.model_cache_dir / f"{cache_key}.pkl"
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(model, f)
            logger.info(f"Model saved to cache: {cache_key}")
        except Exception as e:
            logger.error(f"Error saving model to cache: {e}")
    
    def _load_model(self, cache_key: str) -> Optional[Any]:
        """Load model from cache"""
        cache_path = self.model_cache_dir / f"{cache_key}.pkl"
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    model = pickle.load(f)
                logger.info(f"Model loaded from cache: {cache_key}")
                return model
            except Exception as e:
                logger.error(f"Error loading model from cache: {e}")
        return None
    
    def prepare_sales_data(self, db: Session, days: int = 90) -> List[Dict[str, Any]]:
        """Prepare sales data for forecasting from database"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        orders = db.query(
            func.date(Order.created_at).label('date'),
            func.sum(Order.total_amount).label('revenue'),
            func.count(Order.id).label('orders')
        ).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped', 'Out for Delivery'])
        ).group_by(func.date(Order.created_at)).all()
        
        data = []
        for order in orders:
            data.append({
                'date': str(order.date),
                'revenue': float(order.revenue),
                'orders': order.orders
            })
        
        # Sort by date
        data.sort(key=lambda x: x['date'])
        return data
    
    def prepare_inventory_data(self, db: Session, product_id: int = None, days: int = 90) -> List[Dict[str, Any]]:
        """Prepare inventory demand data for forecasting"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        query = db.query(
            func.date(Order.created_at).label('date'),
            OrderItem.product_id,
            func.sum(OrderItem.quantity).label('quantity')
        ).join(Order, Order.id == OrderItem.order_id).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        )
        
        if product_id:
            query = query.filter(OrderItem.product_id == product_id)
        
        orders = query.group_by(func.date(Order.created_at), OrderItem.product_id).all()
        
        data = []
        for order in orders:
            data.append({
                'date': str(order.date),
                'product_id': order.product_id,
                'quantity': order.quantity
            })
        
        # Sort by date
        data.sort(key=lambda x: x['date'])
        return data
    
    def _check_data_sufficiency(self, data: List[Dict[str, Any]], model_type: str) -> Tuple[bool, str]:
        """Check if sufficient data exists for forecasting"""
        min_points = {
            'prophet': self.MIN_DATA_POINTS_PROPHET,
            'arima': self.MIN_DATA_POINTS_ARIMA,
            'lstm': self.MIN_DATA_POINTS_LSTM
        }
        
        logger.info(f"Checking data sufficiency for {model_type}: received {len(data) if data else 0} records")
        
        if not data:
            return False, f"No data available for {model_type} forecasting"
        
        if len(data) < min_points.get(model_type, 30):
            return False, f"Insufficient data for {model_type}: need at least {min_points[model_type]} data points, got {len(data)}"
        
        # Check for valid revenue values
        revenues = [d.get('revenue', 0) for d in data if d.get('revenue') is not None]
        if not revenues or all(r == 0 for r in revenues):
            return False, "All revenue values are zero or missing, cannot generate forecast"
        
        logger.info(f"Data sufficient for {model_type}: {len(data)} records with valid revenues")
        return True, "Data sufficient"
    
    def forecast_sales_prophet(self, data: List[Dict], periods: int = 30) -> Dict[str, Any]:
        """Forecast sales using Prophet model with real training and evaluation"""
        try:
            # Fix for NumPy 2.0 compatibility - add deprecated type aliases
            import numpy as np
            if not hasattr(np, 'float_'):
                np.float_ = np.float64
            if not hasattr(np, 'int_'):
                np.int_ = np.int64

            from prophet import Prophet
            import pandas as pd
            
            # Check data sufficiency
            is_sufficient, message = self._check_data_sufficiency(data, 'prophet')
            if not is_sufficient:
                return {
                    'model': 'Prophet',
                    'forecast': [],
                    'error': message,
                    'data_sufficient': False,
                    'metrics': {}
                }
            
            # Preprocess data
            data = self.preprocessor.handle_missing_dates(data)
            data = self.preprocessor.remove_outliers(data)
            
            # Prepare data for Prophet
            df_prophet = pd.DataFrame(data)
            df_prophet = df_prophet.rename(columns={'date': 'ds', 'revenue': 'y'})
            df_prophet['ds'] = pd.to_datetime(df_prophet['ds'])
            
            # Check cache
            data_hash = self._compute_data_hash(data)
            cache_key = self._get_cache_key(data_hash, 'prophet')
            cached_model = self._load_model(cache_key)
            
            if cached_model:
                model = cached_model
                logger.info("Using cached Prophet model")
            else:
                # Fit model with hyperparameters
                model = Prophet(
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=len(data) >= 365,
                    seasonality_mode='multiplicative',
                    changepoint_prior_scale=0.05,
                    seasonality_prior_scale=10.0
                )
                model.fit(df_prophet)
                self._save_model(model, cache_key)
            
            # Make future dataframe
            future = model.make_future_dataframe(periods=periods)
            forecast = model.predict(future)
            
            # Extract forecast for future periods only
            forecast_data = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(periods)
            
            # Calculate metrics on training data
            train_forecast = forecast[['ds', 'yhat']].iloc[:-periods]
            train_forecast = train_forecast.merge(df_prophet, on='ds', how='inner')
            if len(train_forecast) > 0:
                metrics = self.evaluator.calculate_metrics(
                    train_forecast['y'].values,
                    train_forecast['yhat'].values
                )
            else:
                metrics = {}
            
            # Prepare forecast records
            forecast_records = []
            for _, row in forecast_data.iterrows():
                forecast_records.append({
                    'ds': row['ds'].strftime('%Y-%m-%d') if hasattr(row['ds'], 'strftime') else str(row['ds']),
                    'yhat': max(0, float(row['yhat'])),
                    'yhat_lower': max(0, float(row['yhat_lower'])),
                    'yhat_upper': max(0, float(row['yhat_upper']))
                })
            
            return {
                'model': 'Prophet',
                'forecast': forecast_records,
                'data_sufficient': True,
                'metrics': metrics,
                'confidence_interval': True,
                'trend': float(forecast['trend'].iloc[-1]) if len(forecast) > 0 else 0,
                'seasonal_components': {
                    'weekly': float(forecast['weekly'].iloc[-1]) if 'weekly' in forecast.columns else 0,
                    'yearly': float(forecast['yearly'].iloc[-1]) if 'yearly' in forecast.columns else 0
                }
            }
        except ImportError as e:
            logger.error(f"Prophet not installed: {e}")
            return {
                'model': 'Prophet',
                'forecast': [],
                'error': 'Prophet library not installed. Install with: pip install prophet',
                'data_sufficient': False,
                'metrics': {}
            }
        except Exception as e:
            logger.error(f"Prophet forecast error: {e}")
            return {
                'model': 'Prophet',
                'forecast': [],
                'error': str(e),
                'data_sufficient': False,
                'metrics': {}
            }
    
    def forecast_sales_arima(self, data: List[Dict], periods: int = 30) -> Dict[str, Any]:
        """Forecast sales using ARIMA model with real training and evaluation"""
        try:
            from statsmodels.tsa.arima.model import ARIMA
            from statsmodels.tsa.stattools import adfuller
            import pandas as pd
            import warnings
            warnings.filterwarnings('ignore')
            
            # Check data sufficiency
            is_sufficient, message = self._check_data_sufficiency(data, 'arima')
            if not is_sufficient:
                return {
                    'model': 'ARIMA',
                    'forecast': [],
                    'error': message,
                    'data_sufficient': False,
                    'metrics': {}
                }
            
            # Preprocess data
            data = self.preprocessor.handle_missing_dates(data)
            data = self.preprocessor.remove_outliers(data)
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # Prepare time series
            ts = df.set_index('date')['revenue']
            
            # Check for stationarity
            try:
                adf_result = adfuller(ts.dropna())
                is_stationary = adf_result[1] < 0.05
                d_param = 0 if is_stationary else 1
            except:
                d_param = 1
            
            # Check cache
            data_hash = self._compute_data_hash(data)
            cache_key = self._get_cache_key(data_hash, 'arima')
            cached_model = self._load_model(cache_key)
            
            if cached_model:
                model_fit = cached_model
                logger.info("Using cached ARIMA model")
            else:
                # Fit ARIMA model with auto order selection
                model = ARIMA(ts, order=(1, d_param, 1))
                model_fit = model.fit()
                self._save_model(model_fit, cache_key)
            
            # Make forecast with confidence intervals
            forecast_result = model_fit.get_forecast(steps=periods)
            forecast = forecast_result.predicted_mean
            conf_int = forecast_result.conf_int()
            
            # Calculate metrics on training data
            train_pred = model_fit.fittedvalues
            if len(train_pred) > 0:
                metrics = self.evaluator.calculate_metrics(
                    ts.values[:len(train_pred)],
                    train_pred.values
                )
            else:
                metrics = {}
            
            # Prepare forecast data
            last_date = df['date'].iloc[-1]
            forecast_dates = [last_date + timedelta(days=i+1) for i in range(periods)]
            
            forecast_data = []
            for i, (date, value) in enumerate(zip(forecast_dates, forecast)):
                forecast_data.append({
                    'ds': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                    'yhat': max(0, float(value)),
                    'yhat_lower': max(0, float(conf_int.iloc[i, 0])),
                    'yhat_upper': max(0, float(conf_int.iloc[i, 1]))
                })
            
            return {
                'model': 'ARIMA',
                'forecast': forecast_data,
                'data_sufficient': True,
                'metrics': metrics,
                'confidence_interval': True,
                'aic': float(model_fit.aic),
                'bic': float(model_fit.bic),
                'order': (1, d_param, 1),
                'is_stationary': d_param == 0
            }
        except ImportError as e:
            logger.error(f"statsmodels not installed: {e}")
            return {
                'model': 'ARIMA',
                'forecast': [],
                'error': 'statsmodels library not installed. Install with: pip install statsmodels',
                'data_sufficient': False,
                'metrics': {}
            }
        except Exception as e:
            logger.error(f"ARIMA forecast error: {e}")
            return {
                'model': 'ARIMA',
                'forecast': [],
                'error': str(e),
                'data_sufficient': False,
                'metrics': {}
            }
    
    def forecast_sales_lstm(self, data: List[Dict], periods: int = 30) -> Dict[str, Any]:
        """Forecast sales using LSTM model with real training and evaluation"""
        try:
            from sklearn.preprocessing import MinMaxScaler
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout
            from tensorflow.keras.callbacks import EarlyStopping
            import pandas as pd
            import warnings
            warnings.filterwarnings('ignore')
            
            # Check data sufficiency
            is_sufficient, message = self._check_data_sufficiency(data, 'lstm')
            if not is_sufficient:
                return {
                    'model': 'LSTM',
                    'forecast': [],
                    'error': message,
                    'data_sufficient': False,
                    'metrics': {}
                }
            
            # Preprocess data
            data = self.preprocessor.handle_missing_dates(data)
            data = self.preprocessor.remove_outliers(data)
            data = self.preprocessor.add_rolling_features(data)
            data = self.preprocessor.add_lag_features(data)
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # Prepare data
            ts = df['revenue'].values.reshape(-1, 1)
            
            # Scale data
            scaler = MinMaxScaler(feature_range=(0, 1))
            ts_scaled = scaler.fit_transform(ts)
            
            # Create sequences
            look_back = min(14, len(data) // 3)
            X, y = self._create_sequences(ts_scaled, look_back)
            
            # Split into train and test
            split_idx = int(len(X) * 0.8)
            X_train, X_test = X[:split_idx], X[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]
            
            # Check cache
            data_hash = self._compute_data_hash(data)
            cache_key = self._get_cache_key(data_hash, 'lstm')
            cached_model = self._load_model(cache_key)
            
            if cached_model:
                model = cached_model
                logger.info("Using cached LSTM model")
            else:
                # Build LSTM model
                model = Sequential([
                    LSTM(64, activation='relu', return_sequences=True, input_shape=(look_back, 1)),
                    Dropout(0.2),
                    LSTM(32, activation='relu', return_sequences=False),
                    Dropout(0.2),
                    Dense(16, activation='relu'),
                    Dense(1)
                ])
                
                model.compile(optimizer='adam', loss='mse', metrics=['mae'])
                
                # Train with early stopping
                early_stopping = EarlyStopping(
                    monitor='val_loss',
                    patience=10,
                    restore_best_weights=True
                )
                
                model.fit(
                    X_train, y_train,
                    epochs=100,
                    batch_size=16,
                    validation_data=(X_test, y_test),
                    callbacks=[early_stopping],
                    verbose=0
                )
                
                self._save_model(model, cache_key)
            
            # Evaluate on test set
            if len(X_test) > 0:
                test_predictions = model.predict(X_test, verbose=0)
                test_predictions = scaler.inverse_transform(test_predictions)
                y_test_actual = scaler.inverse_transform(y_test.reshape(-1, 1))
                
                metrics = self.evaluator.calculate_metrics(
                    y_test_actual.flatten(),
                    test_predictions.flatten()
                )
            else:
                metrics = {}
            
            # Make forecast
            forecast_scaled = []
            last_sequence = ts_scaled[-look_back:].reshape(1, look_back, 1)
            
            for _ in range(periods):
                pred = model.predict(last_sequence, verbose=0)
                forecast_scaled.append(pred[0, 0])
                last_sequence = np.roll(last_sequence, -1, axis=1)
                last_sequence[0, -1, 0] = pred[0, 0]
            
            # Inverse scale
            forecast = scaler.inverse_transform(np.array(forecast_scaled).reshape(-1, 1))
            
            # Calculate prediction intervals using historical residuals
            if len(y_test_actual) > 0:
                residuals = np.abs(y_test_actual.flatten() - test_predictions.flatten())
                std_residual = np.std(residuals)
            else:
                std_residual = np.std(ts) * 0.1
            
            # Prepare forecast data
            last_date = df['date'].iloc[-1]
            forecast_dates = [last_date + timedelta(days=i+1) for i in range(periods)]
            
            forecast_data = []
            for date, value in zip(forecast_dates, forecast):
                forecast_data.append({
                    'ds': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                    'yhat': max(0, float(value)),
                    'yhat_lower': max(0, float(value) - 1.96 * std_residual),
                    'yhat_upper': max(0, float(value) + 1.96 * std_residual)
                })
            
            return {
                'model': 'LSTM',
                'forecast': forecast_data,
                'data_sufficient': True,
                'metrics': metrics,
                'confidence_interval': True,
                'look_back': look_back,
                'epochs': 100,
                'architecture': 'LSTM(64)-Dropout-LSTM(32)-Dropout-Dense(16)-Dense(1)'
            }
        except ImportError as e:
            logger.error(f"TensorFlow not installed: {e}")
            return {
                'model': 'LSTM',
                'forecast': [],
                'error': 'TensorFlow not installed. Install with: pip install tensorflow',
                'data_sufficient': False,
                'metrics': {}
            }
        except Exception as e:
            logger.error(f"LSTM forecast error: {e}")
            return {
                'model': 'LSTM',
                'forecast': [],
                'error': str(e),
                'data_sufficient': False,
                'metrics': {}
            }
    
    def _create_sequences(self, data, look_back):
        """Create sequences for LSTM training"""
        X, y = [], []
        for i in range(len(data) - look_back):
            X.append(data[i:i+look_back])
            y.append(data[i+look_back])
        return np.array(X), np.array(y)
    
    def compare_models(self, forecasts: List[Dict]) -> Dict[str, Any]:
        """Compare different forecasting models and select best based on metrics"""
        comparison = []
        
        for forecast in forecasts:
            model_name = forecast['model']
            forecast_data = forecast['forecast']
            metrics = forecast.get('metrics', {})
            
            if forecast_data and forecast.get('data_sufficient', False):
                avg_forecast = sum(f['yhat'] for f in forecast_data) / len(forecast_data)
                
                # Calculate variance
                values = [f['yhat'] for f in forecast_data]
                mean = avg_forecast
                variance = sum((x - mean) ** 2 for x in values) / len(values) if values else 0
                
                # Calculate composite score (lower is better for errors, higher for R²)
                score = 0
                if metrics:
                    # Normalize metrics (lower MAE/RMSE/MAPE is better, higher R² is better)
                    mae_norm = metrics.get('mae', float('inf')) / 10000 if metrics.get('mae') else 1
                    rmse_norm = metrics.get('rmse', float('inf')) / 10000 if metrics.get('rmse') else 1
                    mape_norm = metrics.get('mape', 100) / 100
                    r2_norm = 1 - metrics.get('r2', 0) if metrics.get('r2') else 1
                    
                    score = (mae_norm + rmse_norm + mape_norm + r2_norm) / 4
                
                comparison.append({
                    'model': model_name,
                    'avg_forecast': round(avg_forecast, 2),
                    'variance': round(variance, 2),
                    'confidence_interval': forecast.get('confidence_interval', False),
                    'metrics': metrics,
                    'score': round(score, 4),
                    'data_sufficient': forecast.get('data_sufficient', False)
                })
        
        # Select best model based on composite score
        valid_models = [c for c in comparison if c['data_sufficient'] and c['metrics']]
        if valid_models:
            best_model = min(valid_models, key=lambda x: x['score'])['model']
        else:
            best_model = None
        
        return {
            'comparison': comparison,
            'best_model': best_model,
            'best_model_reason': 'Lowest composite error score and highest R²' if best_model else 'No valid models available'
        }
    
    def get_seasonal_forecast(self, db: Session) -> Dict[str, Any]:
        """Get seasonal forecasting insights from real data"""
        # Get monthly data
        monthly_data = db.query(
            func.strftime('%Y-%m', Order.created_at).label('month'),
            func.sum(Order.total_amount).label('revenue')
        ).filter(
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(func.strftime('%Y-%m', Order.created_at)).all()
        
        # Identify seasonal patterns
        months = {}
        for data in monthly_data:
            month_num = int(data.month.split('-')[1])
            months[month_num] = float(data.revenue)
        
        # Seasonal insights
        seasonal_insights = []
        if months:
            avg_revenue = sum(months.values()) / len(months)
            
            for month, revenue in months.items():
                if revenue > avg_revenue * 1.2:
                    seasonal_insights.append({
                        'month': month,
                        'type': 'peak',
                        'message': f"Month {month} is a peak season with {((revenue/avg_revenue - 1) * 100):.1f}% above average"
                    })
                elif revenue < avg_revenue * 0.8:
                    seasonal_insights.append({
                        'month': month,
                        'type': 'low',
                        'message': f"Month {month} is a low season with {((1 - revenue/avg_revenue) * 100):.1f}% below average"
                    })
        
        return {
            'monthly_data': months,
            'seasonal_insights': seasonal_insights,
            'avg_monthly_revenue': round(sum(months.values()) / len(months), 2) if months else 0,
            'data_points': len(months)
        }
    
    def detect_anomalies(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect anomalies in the data using statistical methods"""
        if len(data) < 10:
            return []
        
        import pandas as pd
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # Calculate rolling statistics
        df['rolling_mean'] = df['revenue'].rolling(window=7, center=True).mean()
        df['rolling_std'] = df['revenue'].rolling(window=7, center=True).std()
        
        # Detect anomalies (values beyond 2 standard deviations)
        anomalies = []
        for _, row in df.iterrows():
            if pd.notna(row['rolling_mean']) and pd.notna(row['rolling_std']):
                z_score = abs((row['revenue'] - row['rolling_mean']) / row['rolling_std'])
                if z_score > 2:
                    anomalies.append({
                        'date': row['date'].strftime('%Y-%m-%d'),
                        'value': float(row['revenue']),
                        'expected': float(row['rolling_mean']),
                        'z_score': float(z_score),
                        'type': 'high' if row['revenue'] > row['rolling_mean'] else 'low'
                    })
        
        return anomalies
    
    def train_and_forecast(self, db: Session, model_type: str = 'all', periods: int = 30, custom_data: List[Dict] = None) -> Dict[str, Any]:
        """Train models and generate forecasts with real data only"""
        # Use custom data if provided, otherwise use database data
        sales_data = custom_data if custom_data else self.prepare_sales_data(db)
        
        logger.info(f"train_and_forecast called with {len(sales_data) if sales_data else 0} records from {'custom' if custom_data else 'database'}")
        
        # Check if data exists
        if not sales_data:
            return {
                'forecasts': [],
                'comparison': {'comparison': [], 'best_model': None, 'best_model_reason': 'No data available'},
                'seasonal_insights': {'monthly_data': {}, 'seasonal_insights': [], 'avg_monthly_revenue': 0, 'data_points': 0},
                'data_source': 'custom' if custom_data else 'database',
                'data_points': 0,
                'data_sufficient': False,
                'error': 'No data available for forecasting. Please upload historical sales data or ensure orders exist in the database.',
                'warning': 'Insufficient data: Cannot generate forecasts without historical sales data'
            }
        
        # Detect anomalies
        anomalies = self.detect_anomalies(sales_data)
        
        forecasts = []
        
        # Train Prophet
        if model_type in ['prophet', 'all']:
            prophet_forecast = self.forecast_sales_prophet(sales_data, periods)
            forecasts.append(prophet_forecast)
        
        # Train ARIMA
        if model_type in ['arima', 'all']:
            arima_forecast = self.forecast_sales_arima(sales_data, periods)
            forecasts.append(arima_forecast)
        
        # Train LSTM
        if model_type in ['lstm', 'all']:
            lstm_forecast = self.forecast_sales_lstm(sales_data, periods)
            forecasts.append(lstm_forecast)
        
        # Compare models
        comparison = self.compare_models(forecasts)
        
        # Get seasonal insights
        seasonal = self.get_seasonal_forecast(db) if not custom_data else {'monthly_data': {}, 'seasonal_insights': [], 'avg_monthly_revenue': 0, 'data_points': 0}
        
        # Check if any model succeeded
        successful_models = [f for f in forecasts if f.get('data_sufficient', False)]
        
        return {
            'forecasts': forecasts,
            'comparison': comparison,
            'seasonal_insights': seasonal,
            'data_source': 'custom' if custom_data else 'database',
            'data_points': len(sales_data),
            'data_sufficient': len(successful_models) > 0,
            'anomalies': anomalies,
            'warning': None if successful_models else f'All models failed due to insufficient data. Need at least {self.MIN_DATA_POINTS_ARIMA} data points for ARIMA, {self.MIN_DATA_POINTS_PROPHET} for Prophet, or {self.MIN_DATA_POINTS_LSTM} for LSTM.',
            'recommendation': f'Best model: {comparison["best_model"]}' if comparison['best_model'] else 'No model could be trained with available data'
        }

    def forecast_revenue(self, db: Session, days: int = 30) -> Dict[str, Any]:
        """Generate revenue forecast for the next N days

        This is a convenience method that calls train_and_forecast and formats
        the output for the dashboard API.

        Returns:
            Dict with daily_forecasts, trend, and confidence_intervals
        """
        result = self.train_and_forecast(db, model_type='all', periods=days)

        # Check if we have any successful forecasts
        successful_forecasts = [f for f in result.get('forecasts', []) if f.get('data_sufficient', False)]

        if not successful_forecasts:
            logger.warning(f"No successful forecasts available. Data points: {result.get('data_points', 0)}")
            return {
                'daily_forecasts': [],
                'trend': 'stable',
                'confidence_intervals': {'average': 0},
                'error': result.get('warning', 'No forecast data available'),
                'data_points': result.get('data_points', 0)
            }

        # Use the best model or the first successful one
        best_model_name = result.get('comparison', {}).get('best_model')
        best_forecast = None

        if best_model_name:
            for f in successful_forecasts:
                if f.get('model') == best_model_name:
                    best_forecast = f
                    break

        if not best_forecast:
            best_forecast = successful_forecasts[0]

        # Format the forecast data for the dashboard
        forecast_records = best_forecast.get('forecast', [])
        daily_forecasts = []

        for record in forecast_records:
            daily_forecasts.append({
                'date': record.get('ds', ''),
                'forecast': record.get('yhat', 0),
                'lower': record.get('yhat_lower', 0),
                'upper': record.get('yhat_upper', 0)
            })

        # Determine trend
        trend_value = best_forecast.get('trend', 0)
        if trend_value > 0.01:
            trend = 'upward'
        elif trend_value < -0.01:
            trend = 'downward'
        else:
            trend = 'stable'

        # Calculate average confidence
        metrics = best_forecast.get('metrics', {})
        r2_score = metrics.get('r2', 0)
        confidence = max(0, min(100, int(r2_score * 100))) if r2_score else 85

        return {
            'daily_forecasts': daily_forecasts,
            'trend': trend,
            'confidence_intervals': {
                'average': confidence,
                'lower_bound': sum(d['lower'] for d in daily_forecasts) / len(daily_forecasts) if daily_forecasts else 0,
                'upper_bound': sum(d['upper'] for d in daily_forecasts) / len(daily_forecasts) if daily_forecasts else 0
            },
            'model_used': best_forecast.get('model', 'Unknown'),
            'metrics': metrics,
            'data_points': result.get('data_points', 0)
        }


demand_forecasting_service = DemandForecastingService()