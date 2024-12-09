from flask import Flask, request, jsonify
import time
import cv2
import numpy as np
from PIL import Image
import easyocr
import re
from playwright.sync_api import sync_playwright
import threading

# Initialize Flask app
app = Flask(__name__)

# Hardcoded credentials
USERNAME = "monadwa999@gmail.com"
PASSWORD = "Monadwa999$"

# Initialize the reader object for English
reader = easyocr.Reader(['en'])

# Cache to store appointment data
appointment_cache = {}
last_refresh_time = 0
refresh_interval = 600  # 10 minutes (600 seconds)

# Function to refresh appointment data every 10 minutes
def refresh_appointment_data():
    global appointment_cache, last_refresh_time
    while True:
        current_time = time.time()
        # Check if it's time to refresh the data
        if current_time - last_refresh_time > refresh_interval:
            print("Refreshing appointment data...")
            locations = ["Riyadh", "Jeddah", "Al Khobar"]
            results = {}
            for location in locations:
                print(f"Checking for location: {location}")
                header, times = login_and_check_appointments(location=location)
                if header and times:
                    results[location] = {"header": header, "times": times}
                else:
                    results[location] = {"error": f"Could not retrieve appointment slots for {location}."}
            # Update the cache and refresh time
            appointment_cache = results
            last_refresh_time = current_time
        time.sleep(60)  # Sleep for 1 minute before checking again

# Start a separate thread for refreshing appointment data
threading.Thread(target=refresh_appointment_data, daemon=True).start()

# Function to log in using Playwright and capture the first available appointment time slot
def login_and_check_appointments(location="Riyadh"):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Set headless=True in production for headless mode
        page = browser.new_page()
        try:
            print("Opening the website...")
            page.goto('https://visas-de.tlscontact.com/visa/sa', timeout=60000)
            print("Page loaded.")

            # Select location
            print(f"Selecting location: {location}")
            if location.lower() == "al khobar":
                page.click("text=Al-Khobar")
            elif location.lower() == "jeddah":
                page.click("text=Jeddah")
            elif location.lower() == "riyadh":
                page.click("text=Riyadh")
            else:
                return f"Invalid location: {location}. Please select a valid location."

            # Wait for page to load after location selection
            page.wait_for_load_state('networkidle', timeout=60000)
            print(f"Location {location} selected.")

            # Click LOGIN button
            print("Attempting to click LOGIN...")
            page.wait_for_selector('text=LOGIN', timeout=60000)
            page.click('text=LOGIN')
            print("Clicked LOGIN.")

            # Enter credentials and log in
            page.wait_for_selector('input[name="username"]', timeout=60000)
            page.fill('input[name="username"]', USERNAME)
            page.fill('input[name="password"]', PASSWORD)
            print("Entering credentials...")

            # Simulate pressing the Enter key to submit the form
            page.press('input[name="password"]', 'Enter')
            print("Form submitted (Enter key pressed).")

            # Wait for redirection after login
            page.wait_for_load_state('networkidle', timeout=60000)
            print("Successfully logged in and page redirected.")

            # Click the "Enter" button
            print("Locating all elements with the class 'tls-button-primary'...")
            enter_buttons = page.locator('.tls-button-primary').all()

            if len(enter_buttons) > 0:
                print("Attempting to click the first 'Enter' button using JavaScript...")
                enter_buttons[0].scroll_into_view_if_needed()  # Ensure the button is visible
                time.sleep(1)  # Wait for any animations or loading
                enter_buttons[0].click()  # Click the first button
                print("Successfully clicked the first 'Enter' button.")
            else:
                print("Unable to locate any 'Enter' button with the specified class name.")

            # Click the "Book appointment" button
            print("Attempting to click 'Book appointment' button...")
            page.wait_for_selector("button:has-text('Book appointment')", timeout=60000)
            book_appointment_button = page.locator("button:has-text('Book appointment')")
            book_appointment_button.scroll_into_view_if_needed()
            time.sleep(1)
            book_appointment_button.click()
            print("'Book appointment' button clicked.")

            # Wait for the specific time picker section to load
            print("Locating time picker group...")
            page.wait_for_selector('.tls-time-picker--time-group', timeout=60000)
            time.sleep(3)
            # Target the first time slot inside the time picker section
            time_picker_group = page.locator('.tls-time-picker--time-group').first
            first_time_slot = time_picker_group.locator('.tls-time-group--slot').first # Get the first slot within the group
            time.sleep(3)
            # Extract the first available time slot (using the text or image capture method)
            time_slot_text = first_time_slot.inner_text()
            print(f"First time slot text: {time_slot_text}")
            # Zoom out the page
            page.evaluate("document.body.style.zoom='0.95'")
            # Take a screenshot of the time slot
            screenshot_path = 'appointment_time_picker_first_slot.png'
            first_time_slot.screenshot(path=screenshot_path)
            print("Screenshot of the first time slot saved.")


            # Process the image to extract text from the highlighted (colored) area of the time slot
            highlighted_header, highlighted_times = process_image_for_highlighted_texts(screenshot_path)

            # Return the extracted highlighted time slots
            return highlighted_header, highlighted_times

        except Exception as e:
            return f"An error occurred: {str(e)}", None
        finally:
            browser.close()


# Function to process image and extract highlighted text (colored time slots)
def process_image_for_highlighted_texts(image_path):
    # Load the image using OpenCV
    image = cv2.imread(image_path)

    # Convert the image from BGR to RGB
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Define the range for white color in RGB (this will be used for non-white time slots)
    lower_white = np.array([200, 200, 200])  # Lower bound of white
    upper_white = np.array([255, 255, 255])  # Upper bound of white

    # Create a mask for white regions (to skip white slots)
    white_mask = cv2.inRange(rgb_image, lower_white, upper_white)

    # Invert the mask to get non-white regions (blue-highlighted cells)
    non_white_mask = cv2.bitwise_not(white_mask)

    # Find contours of the non-white areas (highlighted cells)
    contours, _ = cv2.findContours(non_white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Sort contours from top to bottom
    contours = sorted(contours, key=lambda cnt: cv2.boundingRect(cnt)[1])

    # List to store extracted text from non-white regions (highlighted cells)
    header_texts = []
    time_slots = []

    # Adjust the region to capture the full column, starting a little higher
    # You can set the range higher than 120 if required, like 150 or more
    header_region = rgb_image[0:160, :]  # Adjusted to capture more of the upper side
    header_result = reader.readtext(header_region)

    # Extract the header text manually
    for detection in header_result:
        text = detection[1].strip()
        # Only append non-empty text and ignore time-like entries (e.g., "09:00" or "09:30")
        if text and not re.match(r'^\d{2}[:.-]\d{2}$', text):  # Ensure no time-like text gets into the header
            header_texts.append(text)

    # Combine header text into a single string (e.g., "DEC. 08\nSunday")
    # Assuming the date is always in the first detected header text and the day in the second.
    if len(header_texts) >= 2:
        header_combined = f"{header_texts[0]}\n{header_texts[1]}\n"
    else:
        header_combined = " ".join(header_texts) + "\n"

    # Regular expression to match valid time format (HH:MM)
    time_pattern = re.compile(r'^\d{2}[:.-]\d{2}$')

    # Process the time slots (blue cells) separately
    for contour in contours:
        # Get the bounding box for the contour
        x, y, w, h = cv2.boundingRect(contour)

        # Crop the non-white region from the original image (for blue cells)
        non_white_region = rgb_image[y:y + h, x:x + w]

        # Convert the cropped region to PIL Image format for OCR
        pil_non_white_region = Image.fromarray(non_white_region)

        # Use OCR to extract the text from the cropped region
        ocr_result = reader.readtext(np.array(pil_non_white_region))

        for detection in ocr_result:
            text = detection[1].strip()

            # Check if the extracted text matches the time format (HH:MM) and append to the time slot list
            if time_pattern.match(text):
                time_slots.append(text)

    return header_combined, time_slots


# Flask route to fetch appointment data from the cache
@app.route('/check', methods=['GET'])
def get_appointments():
    # Check if the cache is empty, meaning data might not have been fetched yet
    if not appointment_cache:
        return jsonify({"message": "Appointment data is still being fetched, please try again later."}), 503

    # Return the cached appointment data
    return jsonify(appointment_cache)


# Run Flask app
if __name__ == '__main__':
    app.run(debug=True)
