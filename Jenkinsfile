pipeline {
    environment {
        GIT_CREDS = credentials('345c79bc-9def-4981-94b5-d8190fdd2304') // as-ci-user.gen
        WEBEX_ROOM = 'Y2lzY29zcGFyazovL3VzL1JPT00vMGEwMDA2YjAtNDQ2ZC0xMWViLWJmODEtMDlmNGNmYTBjNmU3' // Room: H@H Team7 Accordion - CICD Notifications
        WEBEX_CREDS = '0599727a-b4c8-4605-bb91-a7925e3a7ea4'    // cicdnotifier@webex.bot
        // DOCKER_CREDS = 'tbd'
        // DOCKER_REGISTRY_ = 'containers.cisco.com'
        // DOCKER_ORG = 'tbd'
        // DOCKER_REPO = 'tbd'
        // DOCKER_PATH = "$DOCKER_REGISTRY_/$DOCKER_ORG"
        LAB_SERVER_USER = 'cisco'
        LAB_SERVER_IP = '152.22.242.56'
        CMDS = "cd /home/cisco && mv CXHackHome_Team7Accordion_master Team7Accordion-\$(date '+%Y.%m.%d-%H.%M')"
    }
    // agent { label "AMER-REGION && !amer-sio-slv01 && !amer-sio-slv07 && !amer-sio-slv09" }
    agent { label "AMER-REGION" }
    stages {
        stage("Build App") {
            steps {
                echo "Build"
            }
        }
        stage("Code Quality Test") {
            steps {
                echo "Build"
            }
        }
        stage("Deploy to Staging") {
            when {
                anyOf {
                    buildingTag()
                    branch 'master'
                }
                beforeAgent true
            }
            steps {
                echo "Deploy to Staging"

                sshagent(['24c6d4c8-1949-491d-8d9b-ae5f53108bc3']) {
                    // sh "ssh -o StrictHostKeyChecking=no ${DEV_SERVER_USER}@${DEV_SERVER_IP} \"${cmds}\""
                    sh "ssh -o StrictHostKeyChecking=no ${LAB_SERVER_USER}@${LAB_SERVER_IP} -oKexAlgorithms=+diffie-hellman-group1-sha1 -p 8113 \"${CMDS}\""
                    sh "scp -o StrictHostKeyChecking=no -o KexAlgorithms=+diffie-hellman-group1-sha1 -P 8113 -r ${env.WORKSPACE} ${LAB_SERVER_USER}@${LAB_SERVER_IP}:/home/cisco/"
                }
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
