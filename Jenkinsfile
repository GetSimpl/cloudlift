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
                    HASH=$(git rev-parse HEAD | cut -c 1:8)
                    echo $HASH > latest.txt
                '''
            }
        }
        
        stage("Build Docker Image") {
            steps {
                sh '''
                    HASH=$(cat latest.txt)
                    docker build -t cloudlift:${HASH} .
                    TAG=v$(docker run a00761a170cb "--version" | awk '{ print $3}')
                    echo $TAG > tag.txt
                    git tag ${TAG}
                    git push origin refs/tags/${TAG}
                    echo "List of git tag:\n$(git tag -l)"
                    docker tag cloudlift:${HASH} cloudlift:${TAG} .
                '''
            }
        }
        
        stage('Push to Dockerhub') {
	    environment {
                DOCKERHUB_LOGIN = credentials('dockerhub-login')
    	    }
            steps {
                sh '''
                    TAG=$(cat tag.txt)
                    echo "${TAG} is being pushed to dockerhub"
                    docker login -u ${DOCKERHUB_LOGIN_USR} -p ${DOCKERHUB_LOGIN_PSW}
                    docker tag cloudlift:${TAG} rippling/cloudlift:${TAG}
                    echo '{"experimental": "enabled"}' > ~/.docker/config.json
                    docker manifest inspect rippling/cloudlift:${TAG} > /dev/null || docker push rippling/cloudlift:${TAG}

                '''
            }
        }
    }
}
