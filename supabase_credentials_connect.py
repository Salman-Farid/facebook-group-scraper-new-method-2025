import psycopg2

try:
    connection = psycopg2.connect(
        user="postgres.csnwnuxoqzwqsdlpohjg",
        password="?8HZ@CN/3MVwi2$",
        host="aws-0-ap-northeast-2.pooler.supabase.com",
        port=5432,
        dbname="postgres"
    )
    print("Connection successful!")

    cursor = connection.cursor()
    cursor.execute("SELECT NOW();")
    result = cursor.fetchone()
    print("Current Time:", result)

    cursor.close()
    connection.close()
    print("Connection closed.")

except Exception as e:
    print(f"Failed to connect: {e}")