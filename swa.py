import time
import requests
import collections
import re

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException

URL = "https://www.southwest.com/air/booking/select.html"
URL_TIMEOUT = 20

# Preload a dictionary. These are values that are supported by the SWA REST API, but currently unconfigurable
# Some of these can be omitted, but for completeness, I'm including them with default values.
defaultOptions = {
	'returnAirportCode':'',
	'seniorPassengersCount':'0',
	'fareType':'USD',
	'passengerType':'ADULT',
	'promoCode':'',
	'reset':'true',
	'redirectToVision':'true',
	'int':'HOMEQBOMAIR',
	'leapfrogRequest':'true'
}

class scrapeValidation(Exception):
	pass

class scrapeTimeout(Exception):
	pass

class scrapeGeneral(Exception):
	pass

class scrapeDatesNotOpen(Exception):
	pass

def validateAirportCode(airportCode):

	if(not airportCode.isalpha()):
		raise scrapeValidation("validateAirportCode: '" + airportCode + "' contains non-alphabetic characters")

	if(len(airportCode) != 3):
		raise scrapeValidation("validateAirportCode: '" + airportCode + "' can only be 3 characters")

	return airportCode.upper() # No necessary, but prefer to have in upper case

def validateTripType(tripType):

	if((tripType != "roundtrip") and (tripType != "oneway")):
		raise scrapeValidation("validateTripType: '" + tripType + "' not valid, must be 'roundtrip' or 'oneway'")

	return tripType

def validateDate(date):

	pattern = re.compile("^20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]$")
	if(not pattern.match(date)):
		raise scrapeValidation("validateDate: '" + date + "' not in the format YYYY-MM-DD")

	return date

def validateTimeOfDay(timeOfDay):
	validTimes = ['ALL_DAY', 'BEFORE_NOON', 'NOON_TO_SIX', 'AFTER_SIX']

	if(any(x in timeOfDay for x in validTimes)):
		return timeOfDay
	elif(timeOfDay == "anytime"):
		return "ALL_DAY"
	elif(timeOfDay == "morning"):
		return "BEFORE_NOON"
	elif(timeOfDay == "afternoon"):
		return "NOON_TO_SIX"
	elif(timeOfDay == "evening"):
		return "AFTER_SIX"
	else:
		raise scrapeValidation("validateTimeOfDay: '" + timeOfDay + "' invalid")

def validatePassengersCount(passengersCount):
	if( 1 <= passengersCount <= 8):
		return passengersCount
	else:
		raise scrapeValidation("validatePassengersCount: '" + passengersCount + "' must be 1 through 8")

def scrapeFare(element, className):

	fare = element.find_element_by_class_name(className).text
	if(("Unavailable" in fare) or ("Sold out" in fare)):
		return None
	else:
		return int(fare.split("$")[1].split()[0])

def scrapeFlights(flight):

	flightDetails = {}

	flightDetails['flight'] = "".join(flight.find_element_by_class_name("flight-numbers--flight-number").text.split("#")[1].split())

	flightDetails['stops'] = 0	
	flightDetails['origination'] = flight.find_element_by_css_selector("div[type='origination'").text
		# Text here can contain "Next Day", so just take time portion
	flightDetails['destination'] = flight.find_element_by_css_selector("div[type='destination'").text.split()[0]

	durationList = flight.find_element_by_class_name("flight-stops--duration").text.split("Duration",1)[1].split()

		# For flight duration, just round to 2 decimal places - that should be more than enough
	flightDetails['duration'] = round(float(durationList[0].split("h")[0]) +  ((float(durationList[1].split("m")[0])/60.0) + .001), 2)

		# For flights which are non-stop, SWA doesn't display data after the duration
	if(len(durationList) > 2):
		flightDetails['stops'] = int(durationList[2])

		# fare-button_primary-yellow == wannaGetAway
		# fare-button_secondary-light-blue == anytime
		# fare-button_primary-blue == businessSelect
	flightDetails['fare'] = scrapeFare(flight, "fare-button_primary-yellow")
	flightDetails['fareAnytime'] = scrapeFare(flight, "fare-button_secondary-light-blue")
	flightDetails['fareBusinessSelect'] = scrapeFare(flight, "fare-button_primary-blue")

	return flightDetails

def scrape(
	browser,
	originationAirportCode, # 3 letter airport code (eg: MDW - for Midway, Chicago, Illinois)
	destinationAirportCode, # 3 letter airport code (eg: MCO - for Orlando, Florida) 
	departureDate, # Flight departure date in YYYY-MM-DD format
	returnDate, # Flight return date in YYYY-MM-DD format (for roundtip, otherwise ignored)
	tripType = 'roundtrip', # Can be either 'roundtrip' or 'oneway'
	departureTimeOfDay = 'ALL_DAY', # Can be either 'ALL_DAY', 'BEFORE_NOON', 'NOON_TO_SIX', or 'AFTER_SIX' (CASE SENSITIVE)
	returnTimeOfDay = 'ALL_DAY', # Can be either 'ALL_DAY', 'BEFORE_NOON', 'NOON_TO_SIX', or 'AFTER_SIX' (CASE SENSITIVE) 
	adultPassengersCount = 1, # Can be a value of between 1 and 8
	debug = False
	):

	payload = defaultOptions

		# Validate the parameters to ensure nothing is blatently erroneous then load into map
	payload['originationAirportCode'] = validateAirportCode(originationAirportCode)
	payload['destinationAirportCode'] = validateAirportCode(destinationAirportCode)
	payload['tripType'] = validateTripType(tripType)
	payload['departureDate'] = validateDate(departureDate)
	payload['departureTimeOfDay'] = validateTimeOfDay(departureTimeOfDay)
	payload['adultPassengersCount'] = validatePassengersCount(adultPassengersCount)

	if (tripType == 'roundtrip'):
		payload['returnDate'] = validateDate(returnDate)
		payload['returnTimeOfDay'] = validateTimeOfDay(returnTimeOfDay)
	else:
		payload['returnDate'] = '' # SWA REST requires presence of this parameter, even on a 'oneway'

	query =  '&'.join(['%s=%s' % (key, value) for (key, value) in payload.items()])

	fullUrl = URL + '?' + query

	if(browser.type == 'chrome'):
		options = webdriver.ChromeOptions()
		options.binary_location = browser.binaryLocation
		options.add_argument('headless')
		driver = webdriver.Chrome(chrome_options=options)
	else:
		raise scrapeGeneralError("scrape: Unsupported web browser '" + browser.type + "' specified")

	driver.get(fullUrl)

	waitCSS = ".page-error--message, .trip--form-container, "
	waitCSS += "#air-booking-product-1" if tripType == 'roundtrip' else "#air-booking-product-0"

	try:
		element = WebDriverWait(driver, URL_TIMEOUT).until( EC.element_to_be_clickable((By.CSS_SELECTOR, waitCSS)))

	except TimeoutException:
		raise scrapeTimeout("scrape: Timeout occurred after " + str(URL_TIMEOUT) + " seconds waiting for web result")
	except Exception as ex:
		message = "An exception of type {0} occurred. Arguments:\n{1!r}".format(type(ex).__name__, ex.args)
		raise scrapeGeneral("scrape: General exception occurred - " + message)

	if("trip--form-container" in element.get_attribute("class")):
			# If in here, the browser is asking to re-enter flight information, meaning that
			# parameters supplied are most likely 
		raise scrapeValidation("scrape: SWA Website reported what appears to be errors with parameters")
	elif(len(element.find_elements_by_class_name("error-no-routes-exist")) > 0):
			# If in here, this means that most likely, flights haven't opened for this date
		raise scrapeDatesNotOpen("")

	# If here, we should have results, so  parse out...
	priceMatrixes = driver.find_elements_by_class_name("air-booking-select-price-matrix")

	segments = []

	if (payload['tripType'] == 'roundtrip'):
		if (len(priceMatrixes) != 2):
			raise Exception("Only one set of prices returned for round-trip travel")

		outboundSegment = []
		for element in  priceMatrixes[0].find_elements_by_class_name("air-booking-select-detail"):
			outboundSegment.append(scrapeFlights(element))
		segments.append(outboundSegment)	

		returnSegment = []
		for element in  priceMatrixes[1].find_elements_by_class_name("air-booking-select-detail"):
			returnSegment.append(scrapeFlights(element))
		segments.append(returnSegment)

	else:
		outboundSegment = []
		for element in  priceMatrixes[0].find_elements_by_class_name("air-booking-select-detail"):
			outboundSegment.append(scrapeFlights(element))
		segments.append(outboundSegment)

	return segments
