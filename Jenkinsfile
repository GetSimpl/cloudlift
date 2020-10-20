pipeline {
    agent {
        label 'dockerbuild'
    }
    options { disableConcurrentBuilds() }
    stages {
        stage("Tag Cloudlift") {
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
                    git tag ${TAG}
                    git push origin refs/tags/${TAG}
                    echo "List of git tag:\n$(git tag -l)" 
                '''
            }
        }
        
        stage("Build Docker Image") {
            steps {
                sh '''
                    docker build -t cloudlift:${TAG} .
                '''
            }
        }
        
        stage('Push to ECR') {
	    environment {
                DOCKERHUB_LOGIN = credentials('dockerhub-login')
    	    }
            steps {
                sh '''
                    docker login -u ${DOCKERHUB_LOGIN_USR} -p ${DOCKERHUB_LOGIN_PSW}
                    docker tag cloudlift:${TAG} rippling/cloudlift:${TAG}
                    docker push rippling/cloudlift:${TAG}
                '''
            }
        }
    }
}
