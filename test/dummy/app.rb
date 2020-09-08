require 'sinatra'
require 'redis'

get '/' do
  has_ec2_access = system("aws ec2 describe-instances --region us-west-2 --max-items 1") ? "True" : "False"
  begin
    redis_client = Redis.new(host: ENV['REDIS_HOST'])
    "This is dummy app. Label: #{ENV['LABEL']}. Redis PING: #{redis_client.ping}. AWS EC2 READ ACCESS: #{has_ec2_access}"
  rescue => e
    "This is dummy app. Label: #{ENV['LABEL']}. Redis PING: ERROR WHILE CONNECTING. AWS EC2 READ ACCESS: #{has_ec2_access}"
  end
end

get '/elb-check' do
  "This is dummy app. Label: #{ENV['LABEL']}"
end