"""机器学习模块"""
# 延迟导入以避免依赖问题
__all__ = [
    'ConvertibleBondPricer',
    'FeatureEngineer',
    'ModelTrainer',
]

def __getattr__(name):
    if name == 'ConvertibleBondPricer':
        from app.ml.pricing_model import ConvertibleBondPricer
        return ConvertibleBondPricer
    elif name == 'FeatureEngineer':
        from app.ml.feature_engineer import FeatureEngineer
        return FeatureEngineer
    elif name == 'ModelTrainer':
        from app.ml.model_trainer import ModelTrainer
        return ModelTrainer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
