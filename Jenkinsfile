pipeline {
    environment {
        GIT_CREDS = credentials('345c79bc-9def-4981-94b5-d8190fdd2304') // as-ci-user.gen
        WEBEX_ROOM = 'Y2lzY29zcGFyazovL3VzL1JPT00vZTMxNTUzZjAtZDNiMS0xMWViLWJjNzktMTUxMzcwZjZlOTYz' // Sastre - CICD Notifications
        WEBEX_CREDS = '16fdd237-afe3-4d7f-9fe5-7bde6d1275e0'    // sastre-cicd@webex.bot
    }
    agent { label "AMER-REGION" }
    stages {
        stage("Build App") {
            steps {
                echo "Build"
            }
        }
        stage("Code Quality Test") {
            steps {
                echo "Code Quality"
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
