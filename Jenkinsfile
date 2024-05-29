pipeline {
    environment {
        WEBEX_ROOM = 'Y2lzY29zcGFyazovL3VzL1JPT00vZTMxNTUzZjAtZDNiMS0xMWViLWJjNzktMTUxMzcwZjZlOTYz' // Sastre - CICD Notifications
        WEBEX_CREDS = '16fdd237-afe3-4d7f-9fe5-7bde6d1275e0'    // sastre-cicd@webex.bot
        REGISTRY = 'containers.cisco.com'
        REGISTRY_URL = "https://$REGISTRY"
        ECH_ORG = 'maestro-org'
        ECH_REPO = 'sastre-pro'
        GEN_USER = "cx-sastre-user.gen"
        ECH_PATH = "${REGISTRY}/${ECH_ORG}/${ECH_REPO}"
        ECH_CREDENTIALS = 'sastre-ech-token'
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
                echo "Quality test"
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
                    branch 'master'
                }
                beforeAgent true
            }
        }
    }
    post {
        always {
            echo 'Cleanup'
        }
        success {
            sendNotifications('success', WEBEX_ROOM, WEBEX_CREDS)
        }
        unstable {
            sendNotifications('unstable', WEBEX_ROOM, WEBEX_CREDS)
        }
        failure {
            sendNotifications('failure', WEBEX_ROOM, WEBEX_CREDS)
        }
    }
}

def sendNotifications(String status, String room, String creds) {
    def GIT_COMMIT = sh (label: "Get git commit ID", script: "git rev-parse HEAD || true", returnStdout: true).trim()
    def AUTHOR = sh (label: "Get git commit Author", script: "git show -s --pretty=\"%an <%ae>\" ${GIT_COMMIT} || true", returnStdout: true).trim()

    if (status == 'success') {
        icon = "✅"
    } else {
        icon = "❌"
    }
    msg = "${icon} **Build ${env.BUILD_ID} ${status}** <br/> **Jenkins Job**: [${env.JOB_NAME}](${env.BUILD_URL}) <br/> **Change Author**: ${AUTHOR} <br/> **Git Branch**: ${env.BRANCH_NAME} <br/> **Git Commit**: ${GIT_COMMIT} <br/> **GitHub URL**: ${GIT_URL} <br/>"

    sparkSend (
        credentialsId: creds,
        failOnError: false,
        messageType: 'markdown',
        spaceList: [[
            spaceId: room
        ]],
        message: msg
    )
}
