from waitress import serve
from vadrida.wsgi import application

print("Starting Vadrida Server on port 8000...")
print("Press Ctrl+C to stop.")

if __name__ == '__main__':
    serve(application, host='0.0.0.0', port=8000, threads=4)