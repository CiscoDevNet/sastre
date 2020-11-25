#!/bin/sh

if  [ "$SASTRE_ROOT_DIR" ] && [ ! -d "$SASTRE_ROOT_DIR"/rc ] ; then
  cp -R /sastre-init/rc "$SASTRE_ROOT_DIR"
fi

sdwan -h

