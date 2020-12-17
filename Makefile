clean:
	rm -rf dist/* build/* +
	find . -name '*.pyc' -exec rm --force {} +
	find . -name '*.pyo' -exec rm --force {} +

test-template:
		python3 -m pytest test/deployment/service_template_generator_test.py -vv

test-unit:
	pytest -s test/deployment/* test/config/*

test-integration:
	pytest -s test/test_cloudlift.py

package: clean
	python3 setup.py sdist bdist_wheel

package-test-upload: package
	python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*

install-test-package:
	pip install -r requirements.txt
	pip uninstall -y cloudlift
	pip install -U --index-url https://test.pypi.org/simple/ --no-deps cloudlift
	cloudlift --version

package-upload: package
	python3 -m twine upload dist/*
    
package-docker:
	docker build -t cloudlift .