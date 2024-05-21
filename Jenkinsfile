pipeline {
    environment {
        GIT_CREDS = credentials('345c79bc-9def-4981-94b5-d8190fdd2304') // as-ci-user.gen
        WEBEX_ROOM = 'Y2lzY29zcGFyazovL3VzL1JPT00vZTMxNTUzZjAtZDNiMS0xMWViLWJjNzktMTUxMzcwZjZlOTYz' // Sastre - CICD Notifications
        WEBEX_CREDS = '16fdd237-afe3-4d7f-9fe5-7bde6d1275e0'    // sastre-cicd@webex.bot
        REGISTRY = 'containers.cisco.com'
        REGISTRY_URL = "https://$REGISTRY"
        ECH_ORG = 'aide'
        ECH_REPO = 'sastre-pro'
        ECH_PATH = "${REGISTRY}/${ECH_ORG}/${ECH_REPO}"
        ECH_CREDENTIALS = '70d73668-c133-45cc-9943-cc32f1830945'
    }
    agent {
        label "sastre-pro-node"
    }
    stages {
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
                withDockerRegistry([ credentialsId: "$ECH_CREDENTIALS", url: "$REGISTRY_URL" ]) {
                    sh """
                        docker tag $ECH_PATH:$BRANCH_NAME $ECH_PATH:latest
                        docker push $ECH_PATH:latest
                    """
                }
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
