from service import SpxToday

if __name__ == "__main__":
    app = SpxToday(name="spx-today", version="0.1.0")
    app.run()