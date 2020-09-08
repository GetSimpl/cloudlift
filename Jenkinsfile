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
            steps {
                sh '''
                    aws ecr get-login-password --region ${AWS_DEFAULT_REGION} | docker login --username AWS --password-stdin ${AWS_RIPPLING_ACCOUNT}
                    docker tag cloudlift:${TAG} ${AWS_RIPPLING_ACCOUNT}/cloudlift-repo:${TAG}
                    docker push ${AWS_RIPPLING_ACCOUNT}/cloudlift-repo:${TAG}
                '''
            }
        }
    }
}
