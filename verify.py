import requests
import sys

s = requests.Session()

def run_tests():
    # 1. Hit landing page
    res1 = s.get('http://127.0.0.1:5000/?utm_source=test_source&utm_campaign=summer_sale')
    variant = s.cookies.get('ab_variant')
    print(f"Assigned Variant: {variant}")
    if not variant:
        print("FAIL: No variant assigned")
        sys.exit(1)

    # 2. Record landing page view
    res2 = s.post('http://127.0.0.1:5000/api/record_event', json={'event_name': 'visitedLandingPage'})
    print(f"Record PageView: {res2.status_code}")

    # 3. Simulate click
    res3 = s.post('http://127.0.0.1:5000/api/record_event', json={'event_name': 'clickedctabutton'})
    print(f"Record Click: {res3.status_code}")

    # 4. Hit thank you page
    res4 = s.get('http://127.0.0.1:5000/thank-you')
    utm_source = s.cookies.get('utm_source')
    print(f"Persisted UTM: {utm_source}")
    if utm_source != 'test_source':
        print("FAIL: UTM parameters not persisted in cookies correctly")
        sys.exit(1)

    # 5. Record Thank you
    res5 = s.post('http://127.0.0.1:5000/api/record_event', json={'event_name': 'visitedThankYouPage'})
    print(f"Record Conversion: {res5.status_code}")

    # 6. Check analytics
    res6 = s.get('http://127.0.0.1:5000/analytics')
    if 'Click-Through Rate' in res6.text:
        print("Analytics dashboard verified")
    else:
        print("FAIL: Analytics page did not render expected template")
        sys.exit(1)

    print("ALL TESTS PASSED!")

if __name__ == '__main__':
    run_tests()
