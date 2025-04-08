import boto3
import json
import requests

def lambda_handler(event, context):
    # === 1. Försök läsa från Lex (slots) (det som anges i chatten dvs) === ANPASSAS UTEFTER HUR VI BYGGER LEX
    slots = event.get("currentIntent", {}).get("slots", {})

    image_name = slots.get("image_name") if slots else event.get("image_name", "default.jpg")
    location = slots.get("location") if slots else event.get("location", "Uppsala")

    # === 2. Översätt ort till lat/lon ===
    location_coords = {
        "Uppsala": (59.86, 17.64),
        "Stockholm": (59.33, 18.06),
        "Malmö": (55.60, 13.00),
        "Göteborg": (57.71, 11.97),
        "Örebro": (59.27, 15.21)
    }
    lat, lon = location_coords.get(location, (59.86, 17.64))

    # === 3. Hämta väder från SMHI ===
    smhi_url = f"https://opendata-download-metfcst.smhi.se/api/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json"
    weather_response = requests.get(smhi_url)
    weather_data = weather_response.json()
    first_forecast = weather_data["timeSeries"][0]
    parameters = {param["name"]: param["values"][0] for param in first_forecast["parameters"]}
    temp = parameters.get("t", 0)
    rh = parameters.get("r", 0)
    precipitation = parameters.get("pmean", 0)

    # === 4. Bildanalys med Custom Labels ===
    bucket_name = "plant-health-bucket-central"  # <-- ändra till namnet på din bucket
    model_arn = "arn:aws:rekognition:us-east-1:123456789012:project/PotatoHealthClassifier/version/PotatoHealthClassifier.2024-04-08T13.45.12/123456789012"  # <-- byt ut till din riktiga ARN

    s3 = boto3.client("s3")
    rekognition = boto3.client("rekognition", region_name="eu-central-1")

    image_obj = s3.get_object(Bucket=bucket_name, Key=image_name)
    image_bytes = image_obj["Body"].read()

    rekog_response = rekognition.detect_custom_labels(
        ProjectVersionArn=model_arn,
        Image={"Bytes": image_bytes},
        MinConfidence=70
    )

    labels = [label['Name'] for label in rekog_response['CustomLabels']]

    # === 5. Tolka bildens tillstånd ===
    if "LateBlight" in labels:
        diagnosis = "🚨 Potatisplantan visar tydliga tecken på sen bladmögel (Late Blight)."
    elif "EarlyBlight" in labels:
        diagnosis = "⚠️ Potatisplantan visar symptom på tidig bladmögel (Early Blight)."
    elif "Healthy" in labels:
        diagnosis = "✅ Potatisplantan ser frisk ut!"
    else:
        diagnosis = "❓ Kunde inte avgöra plantans hälsa från bilden."

    # === 6. Bedöm blight-risk baserat på väder ===
    if 10 <= temp <= 25 and rh >= 90:
        if temp >= 15:
            blight_risk = "🌧️ Vädret skapar hög risk för bladmögel – håll uppsikt!"
        else:
            blight_risk = "⚠️ Mild risk för blight enligt väderdata."
    else:
        blight_risk = "✅ Låg risk för blight baserat på vädret."

    # === 7. Skapa svarstext ===
    svarstext = (
        f"📍 Plats: {location}\n"
        f"📸 Bild: '{image_name}'\n"
        f"{diagnosis}\n\n"
        f"🌡️ Temperatur: {temp}°C\n"
        f"💧 Luftfuktighet: {rh}%\n"
        f"🌧️ Nederbörd: {precipitation} mm\n\n"
        f"{blight_risk}"
    )

    # === 8. Return – anpassa till Lex eller test ===
    if "currentIntent" in event:
        # Svar till Lex
        return {
            'statusCode': 200,
            'dialogAction': {
                'type': 'Close',
                'fulfillmentState': 'Fulfilled',
                'message': {
                    'contentType': 'PlainText',
                    'content': svarstext
                }
            }
        }
    else:
        # Svar till Lambda test
        return {
            'statusCode': 200,
            'body': json.dumps({
                'image_name': image_name,
                'location': location,
                'diagnosis': diagnosis,
                'blight_risk': blight_risk,
                'weather': {
                    'temperature': temp,
                    'humidity': rh,
                    'precipitation': precipitation
                },
                'labels': labels
            })
        }
