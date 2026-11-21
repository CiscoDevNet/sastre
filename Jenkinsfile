pipeline {
    environment {
        REGISTRY = 'containers.cisco.com'
        REGISTRY_URL = "https://$REGISTRY"
        ECH_ORG = 'maestro-org'
        ECH_REPO = 'sastre-pro'
        GEN_USER = "cx-sastre-user.gen"
        ECH_PATH = "${REGISTRY}/${ECH_ORG}/${ECH_REPO}"
        ECH_CREDENTIALS = 'sastre-ech-token'
        SONAR_TOKEN = 'sonar-token'
    }
    agent {
        label "sastre-pro-node"
    }
    options { timestamps () }

    stages {
        stage('Log Build Info') {
            steps {
                script {
                    def hostname = sh(script: 'hostname', returnStdout: true).trim()
                    def ip = sh(script: 'hostname -I', returnStdout: true).trim()
                    def buildTriggerBy = currentBuild.getBuildCauses()[0].shortDescription

                    echo "Hostname: ${hostname}"
                    echo "IP: ${ip}"
                    echo "Build cause: ${buildTriggerBy}"
                    echo "Build number: ${env.BUILD_NUMBER}"
                    echo "Build URL: ${env.BUILD_URL}"

                    echo "Toolchain Information:"
                    echo "==== podman ===="
                    echo "podman: /usr/bin/podman"
                    sh "podman --version"
                    sh "sha256sum /usr/bin/podman"
                }
            }
        }

        stage("Build") {
            agent {
                dockerfile {
                    additionalBuildArgs "-t $ECH_PATH:$BRANCH_NAME"
                    reuseNode true
                }
            }
            steps {
                echo "Building container..."
            }
        }
        stage("Code Quality Test") {
            steps {
                withCredentials([conjurSecretCredential(credentialsId: "$SONAR_TOKEN", variable: "SONAR_TOKEN")]) {
                    sh """
						docker run --rm --user root -e SONAR_LOGIN=$SONAR_TOKEN -v $PWD:/usr/src:Z \
						sonarsource/sonar-scanner-cli -Dsonar.branch.name=$BRANCH_NAME
                    """
                }
            }
        }
        stage("Publish") {
            options { skipDefaultCheckout true }
            steps {
                withCredentials([conjurSecretCredential(credentialsId: "$ECH_CREDENTIALS", variable: "ECH_TOKEN")]) {
                    sh """
                        echo $ECH_TOKEN | docker login --username $GEN_USER --password-stdin containers.cisco.com
                        docker tag $ECH_PATH:$BRANCH_NAME $ECH_PATH:latest
                        docker push $ECH_PATH:latest
                    """
                }
                echo "Generated Artifact Info:"
                echo "Image name and version: $ECH_PATH:latest"
                sh "docker inspect --format '{{.Digest}}' $ECH_PATH:latest"
                echo "Stored in: $REGISTRY_URL"
                sh "docker rmi $ECH_PATH:$BRANCH_NAME $ECH_PATH:latest"
            }
            when {
                anyOf {
                    buildingTag()
                    branch pattern: "master|dev-.*", comparator: "REGEXP"
                }
                beforeAgent true
            }
        }
    }
    post {
        always {
            echo 'Cleanup'
        }
    }
}
