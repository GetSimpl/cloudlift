pipeline {
    agent {
        label 'dockerbuild'
    }
    options { disableConcurrentBuilds() }
    stages {
        stage("Checkout Cloudlift; get latest hash") {
            steps {
                println params
                sh '''
                    git remote set-url origin git@github.com:Rippling/cloudlift || git remote add origin git@github.com:Rippling/cloudlift
                    if ! [ -z "${COMMIT_ID}" ]; then
                        echo "Checking out custom commit id: ${COMMIT_ID}"
                        git checkout ${COMMIT_ID}
                    fi
                    git fetch --prune origin "+refs/tags/*:refs/tags/*"
                    echo "Tagging this commit: $(git rev-parse HEAD)"
                    HASH=$(git rev-parse HEAD)
                    echo $HASH > latest.txt
                '''
            }
        }
        
        stage("Build Docker Image") {
            steps {
                sh '''
                    HASH=$(cat latest.txt)
                    docker build -t cloudlift:${HASH} .
                    FOUND_TAG=v$(docker run a00761a170cb "--version" | awk '{ print $3}')
                    echo $FOUND_TAG > tag.txt
                    git tag ${FOUND_TAG}
                    git push origin refs/tags/${TAG}
                    echo "List of git tag:\n$(git tag -l)"
                    docker tag cloudlift:${HASH} cloudlift:${FOUND_TAG} .
                '''
            }
        }
        
        stage('Push to Dockerhub') {
	    environment {
                DOCKERHUB_LOGIN = credentials('dockerhub-login')
    	    }
            steps {
                sh '''
                    FOUND_TAG=$(cat tag.txt)
                    echo "${FOUND_TAG} is being pushed to dockerhub"
                    docker login -u ${DOCKERHUB_LOGIN_USR} -p ${DOCKERHUB_LOGIN_PSW}
                    docker tag cloudlift:${FOUND_TAG} rippling/cloudlift:${FOUND_TAG}
                    echo '{"experimental": "enabled"}' > ~/.docker/config.json
                    docker manifest inspect rippling/cloudlift:${FOUND_TAG} > /dev/null || docker push rippling/cloudlift:${FOUND_TAG}

                '''
            }
        }
    }
}
