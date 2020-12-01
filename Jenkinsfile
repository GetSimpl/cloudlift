def VERSION

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
                '''
            }
        }

        stage("Build Docker Image") {
            steps {
                sh """
                    docker build -t cloudlift:build .
                """
                script {
                    VERSION = sh(script: "docker run cloudlift:build --version | awk '{ print \$3 }'", returnStdout: true).trim()
                }
            }
        }
        stage('Tag git') {
            steps {
                sh """
                    git tag ${VERSION}
                    git push origin refs/tags/${VERSION}
                """
            }
        }
        stage('Push to ECR') {
            steps {
                sh """
                    echo "v${VERSION} is being pushed to ECR"
                    aws ecr get-login-password --region ${AWS_DEFAULT_REGION} | docker login --username AWS --password-stdin ${AWS_RIPPLING_ACCOUNT}
                    aws ecr get-login-password --region ${AWS_DEFAULT_REGION} | docker login --username AWS --password-stdin ${INFRA_AWS_RIPPLING_ACCOUNT}

                    docker tag cloudlift:build cloudlift:v${VERSION}

                    docker tag cloudlift:v${VERSION} ${AWS_RIPPLING_ACCOUNT}/cloudlift-repo:v${VERSION}
                    docker tag cloudlift:v${VERSION} ${INFRA_AWS_RIPPLING_ACCOUNT}/cloudlift-repo:v${VERSION}

                    docker push ${AWS_RIPPLING_ACCOUNT}/cloudlift-repo:v${VERSION}
                    docker push ${INFRA_AWS_RIPPLING_ACCOUNT}/cloudlift-repo:v${VERSION}
                """
            }
        }
    }
}
