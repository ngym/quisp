FROM ghcr.io/ngym/quisp-ci:omnetpp-6.3.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /var/run/sshd
RUN id -u vscode >/dev/null 2>&1 || useradd -m -s /bin/bash vscode
RUN echo 'vscode ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vscode
RUN chmod 0440 /etc/sudoers.d/vscode
RUN echo 'root:coffeeplease' | chpasswd
RUN echo 'vscode:morecoffee' | chpasswd
RUN sed -i 's/.*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd
ENV NOTVISIBLE "in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
