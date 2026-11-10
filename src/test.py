import pandas as pd
for f in ["models/predicciones_cv.csv", "models/decisiones_detalle.csv"]:
    d = pd.read_csv(f)
    print(f, d.shape)
    print(d.columns.tolist())
    print(d.head(3).to_string())
    print()